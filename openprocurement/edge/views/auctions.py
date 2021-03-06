# -*- coding: utf-8 -*-

from functools import partial
from openprocurement.api.models import get_now
from openprocurement.api.utils import (
    context_unpack,
    decrypt,
    encrypt,
    json_view,
    APIResource,
)
from openprocurement.edge.utils import eaopresource

try:
    import openprocurement.auctions.core as auctions_core
except:
    auctions_core = None

if auctions_core:
    from openprocurement.auctions.core.design import (
        FIELDS,
        auctions_by_dateModified_view,
        auctions_real_by_dateModified_view,
        auctions_test_by_dateModified_view,
        auctions_by_local_seq_view,
        auctions_real_by_local_seq_view,
        auctions_test_by_local_seq_view,
    )
    VIEW_MAP = {
        u'': auctions_real_by_dateModified_view,
        u'test': auctions_test_by_dateModified_view,
        u'_all_': auctions_by_dateModified_view,
    }
    CHANGES_VIEW_MAP = {
        u'': auctions_real_by_local_seq_view,
        u'test': auctions_test_by_local_seq_view,
        u'_all_': auctions_by_local_seq_view,
    }
    FEED = {
        u'dateModified': VIEW_MAP,
        u'changes': CHANGES_VIEW_MAP,
    }


@eaopresource(name='Auctions',
            path='/auctions',
            description="Open Contracting compatible data exchange format. See http://ocds.open-contracting.org/standard/r/master/#auction for more info")
class AuctionsResource(APIResource):

    def __init__(self, request, context):
        super(AuctionsResource, self).__init__(request, context)
        self.server = request.registry.couchdb_server
        self.update_after = request.registry.update_after

    @json_view(permission='view_auction')
    def get(self):
        """Auctions List

        Get Auctions List
        ----------------

        Example request to get auctions list:

        .. sourcecode:: http

            GET /auctions HTTP/1.1
            Host: example.com
            Accept: application/json

        This is what one should expect in response:

        .. sourcecode:: http

            HTTP/1.1 200 OK
            Content-Type: application/json

            {
                "data": [
                    {
                        "id": "64e93250be76435397e8c992ed4214d1",
                        "dateModified": "2014-10-27T08:06:58.158Z"
                    }
                ]
            }

        """
        # http://wiki.apache.org/couchdb/HTTP_view_API#Querying_Options
        params = {}
        pparams = {}
        fields = self.request.params.get('opt_fields', '')
        if fields:
            params['opt_fields'] = fields
            pparams['opt_fields'] = fields
            fields = fields.split(',')
            view_fields = fields + ['dateModified', 'id']
        limit = self.request.params.get('limit', '')
        if limit:
            params['limit'] = limit
            pparams['limit'] = limit
        limit = int(limit) if limit.isdigit() and (100 if fields else 1000) >= int(limit) > 0 else 100
        descending = bool(self.request.params.get('descending'))
        offset = self.request.params.get('offset', '')
        if descending:
            params['descending'] = 1
        else:
            pparams['descending'] = 1
        feed = self.request.params.get('feed', '')
        view_map = FEED.get(feed, VIEW_MAP)
        changes = view_map is CHANGES_VIEW_MAP
        if feed and feed in FEED:
            params['feed'] = feed
            pparams['feed'] = feed
        mode = self.request.params.get('mode', '')
        if mode and mode in view_map:
            params['mode'] = mode
            pparams['mode'] = mode
        view_limit = limit + 1 if offset else limit
        if changes:
            if offset:
                view_offset = decrypt(self.server.uuid, self.db.name, offset)
                if view_offset and view_offset.isdigit():
                    view_offset = int(view_offset)
                else:
                    self.request.errors.add('params', 'offset', 'Offset expired/invalid')
                    self.request.errors.status = 404
                    return
            if not offset:
                view_offset = 'now' if descending else 0
        else:
            if offset:
                view_offset = offset
            else:
                view_offset = '9' if descending else ''
        list_view = view_map.get(mode, view_map[u''])
        if self.update_after:
            view = partial(list_view, self.db, limit=view_limit, startkey=view_offset, descending=descending, stale='update_after')
        else:
            view = partial(list_view, self.db, limit=view_limit, startkey=view_offset, descending=descending)
        if fields:
            if not changes and set(fields).issubset(set(FIELDS)):
                results = [
                    (dict([(i, j) for i, j in x.value.items() + [('id', x.id), ('dateModified', x.key)] if i in view_fields]), x.key)
                    for x in view()
                ]
            elif changes and set(fields).issubset(set(FIELDS)):
                results = [
                    (dict([(i, j) for i, j in x.value.items() + [('id', x.id)] if i in view_fields]), x.key)
                    for x in view()
                ]
            elif fields:
                self.LOGGER.info('Used custom fields for auctions list: {}'.format(','.join(sorted(fields))),
                            extra=context_unpack(self.request, {'MESSAGE_ID': 'auction_list_custom'}))

                results = [
                    (dict([(k, j) for k, j in i[u'doc'].items() if k in view_fields]), i.key)
                    for i in view(include_docs=True)
                ]
        else:
            results = [
                ({'id': i.id, 'dateModified': i.value['dateModified']} if changes else {'id': i.id, 'dateModified': i.key}, i.key)
                for i in view()
            ]
        if results:
            params['offset'], pparams['offset'] = results[-1][1], results[0][1]
            if offset and view_offset == results[0][1]:
                results = results[1:]
            elif offset and view_offset != results[0][1]:
                results = results[:limit]
                params['offset'], pparams['offset'] = results[-1][1], view_offset
            results = [i[0] for i in results]
            if changes:
                params['offset'] = encrypt(self.server.uuid, self.db.name, params['offset'])
                pparams['offset'] = encrypt(self.server.uuid, self.db.name, pparams['offset'])
        else:
            params['offset'] = offset
            pparams['offset'] = offset
        data = {
            'data': results,
            'next_page': {
                "offset": params['offset'],
                "path": self.request.route_path('Auctions', _query=params),
                "uri": self.request.route_url('Auctions', _query=params)
            }
        }
        if descending or offset:
            data['prev_page'] = {
                "offset": pparams['offset'],
                "path": self.request.route_path('Auctions', _query=pparams),
                "uri": self.request.route_url('Auctions', _query=pparams)
            }
        return data


@eaopresource(name='Auction',
            path='/auctions/{auction_id}',
            description="Open Contracting compatible data exchange format. See http://ocds.open-contracting.org/standard/r/master/#auction for more info")
class AuctionResource(APIResource):

        @json_view(permission='view_auction')
        def get(self):
            del self.request.validated['auction'].__parent__
            del self.request.validated['auction'].rev
            return {'data': self.request.validated['auction']}


@eaopresource(name='Auction Items',
            path='/auctions/{auction_id}/*items',
            description="Open Contracting compatible data exchange format. See http://ocds.open-contracting.org/standard/r/master/#auction for more info")
class AuctionItemsResource(APIResource):

    @json_view(permission='view_auction')
    def get(self):
        return {'data': self.request.validated['item']}
