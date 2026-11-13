class ApiError(Exception):
    def __init__(self, status, code, message, retryable=False, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or []

    def payload(self):
        return dict(code=self.code, message=self.message, retryable=self.retryable, details=self.details)
