from django.conf import settings
import openerplib
import logging

log = logging.getLogger('OESync')



class Oerp():
    '''
    Creates an XMLRPC connection object and offers methods
    to manipulate OpenErp contents.
    '''
    def __init__(self, model_name=None, id=None):
        self.settings = settings.OPENERP_SETTINGS

        self.conn = self._connection()
        self.set_model(model_name)
        self.set_id(id)


    def set_id(self, id):
        self.id = id
        self.exists = self._object_exists()


    def set_model(self, model_name):
        '''
        Creates OpenErp model
        '''
        self.model_name = model_name
        if self.model_name is not None:
            self.model = self.conn.get_model(model_name)
        else:
            self.model = None


    def _connection(self):
        '''
        Returns connection object
        '''
        return(openerplib.get_connection(
            hostname = self.settings['HOST'],
            port = self.settings['PORT'],
            database = self.settings['DB'],
            login = self.settings['USER'],
            password = self.settings['PASSWORD'],
        ))


    def _object_exists(self, id=None):
        '''
        Check whether object with given id exists.
        '''
        if self.model is None:
            return False
        if id is not None:  #set id if provided
            self.id = id
        elif self.id is None:
            return False
        return bool(self.model.exists(self.id))

    def _validate_model(self, model=None):
        if self.model is None:
            raise OerpSyncFailed('No model was provided')
        if model:
            if model != self.model.model_name:
                raise OerpSyncFailed('This method is only available for \'%s\'' % model)

    def _validate_data(self, data):
        if data is None:
            raise OerpSyncFailed('No data was provided')

    def _validate_existence(self):
        if self.exists is False:
            raise OerpSyncFailed('This object does not exist (id %s)' % self.id)



    def delete(self):
        '''
        Deletes OpenErp data for given model and id.
        '''
        self._validate_model()
        try:
            log.info('Deleting from %s (%s)' % (self.model.model_name, self.id))
            self.model.unlink([self.id])
            log.debug('Done.')
        except:
            raise OerpSyncFailed(model=self.model, id=self.id)
        return True


    def create(self, data=None):
        '''
        Create new entry
        '''
        self._validate_model()
        self._validate_data(data)
        try:
            log.info('Creating in %s...' % self.model.model_name)
            log.debug(str(data))
            id = self.model.create(data)
            self.set_id(id)
            log.debug('Done.')
        except Exception as e:
            self.set_id(None)
            raise OerpSyncFailed('Creation failed (improper data?): %s' % e)
        return True


    def update(self, data=None):
        '''
        Update OpenErp data.
        '''
        self._validate_model()
        self._validate_existence()
        try:
            log.info('Updating %s (%s)...' % (self.model.model_name, self.id))
            log.debug(str(data))
            self.model.write(self.id, data)
            log.debug('Done.')
        except:
            raise OerpSyncFailed('Update failed')
        return True

    def confirm_order(self):
        '''
        Confirm order (quote) in OE
        '''
        self._validate_model('sale.order')
        self._validate_existence()
        try:
            log.info('Confirming %s (%s)...' % (self.model.model_name, self.id))
            self.model.action_button_confirm([self.id])
            log.debug('Done.')
        except Exception as e:
            raise OerpSyncFailed('Update failed: %s' % e)
        return True

    def add_payment(self, partner_id, account_id, journal_id, period_id, amount,
                    currency_id=1, company_id=1):
        '''
        Add a payment to an order...
        '''
        self._validate_model('account.voucher')

        try:
            res = self.model.onchange_partner_id([], partner_id, journal_id, 0.0,
                                currency_id, ttype='receipt', date=False)
            vals = {
                'account_id': account_id,
                'amount': amount,
                'company_id': company_id,
                'journal_id': journal_id,
                'partner_id': partner_id,
                'period_id': period_id,
                'type': 'receipt',
            }
            if not res['value']['line_cr_ids']:
                log.warning('No line_cr_ids available')
                res['value']['line_cr_ids'] = [
                    {'type': 'cr', 'account_id': account_id, 'amount':amount}
                ]
            else:
                # Check whether the amount matches a single invoice
                # FIXME: This is probably not the best way of assigning
                # payments to an invoice. Find a better solution here...
                match_id = None
                for i, line in enumerate(res['value']['line_cr_ids']):
                    #remove readonly values
                    del(res['value']['line_cr_ids'][i]['date_original'])
                    del(res['value']['line_cr_ids'][i]['date_due'])

                    if line['amount_unreconciled'] == amount and match_id is None:
                        match_id = i
                #just take the oldest one if no matching amount could be found
                if match_id is None: match_id = 0
                res['value']['line_cr_ids'][match_id]['amount'] = amount

            vals['line_cr_ids']=[(0,0,i) for i in res['value']['line_cr_ids']]

            #create and validate voucher
            self.create(vals)
            log.info('Validating payment')
            self.model.button_proforma_voucher([self.id])
            log.debug('Done.')

        except Exception as e:
            raise OerpSyncFailed('Could not add payment. %s' % e)



    def read(self, fields):
        '''
        Returns content of specific fields
        '''
        self._validate_model()
        self._validate_existence()
        try:
            return self.model.read(self.id, fields)
        except Exception as e:
            raise OerpSyncFailed('Reading failed: %s' % e)

    def validate_invoice(self, invoice_id):
        self._validate_model('account.invoice.confirm')
        try:
            #call invoice validation workflow
            return self.model.invoice_confirm([], {'active_ids': [invoice_id],})
        except Exception as e:
            raise OerpSyncFailed('Validation failed: %s' % e)




class OerpSyncFailed(Exception):
    def __init__(self, msg='', model='unknown model', id='unknown id'):
        self.model = model
        self.id = id
        self.msg = msg
    def __str__(self):
        if self.msg:
            return self.msg
        else:
            return str('%s (%s) could not be synced') % (self.model.model_name,self.id)
