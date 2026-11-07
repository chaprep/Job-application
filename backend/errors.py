class BackendError(Exception):
    def __init__(self, code, message, status=422, retryable=False, fields=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.retryable, self.fields = retryable, fields or {}

    def payload(self):
        return {'error': {'code': self.code, 'message': self.message, 'fields': self.fields, 'retryable': self.retryable}}
