class SuccessService:
  @staticmethod
  def response(response):
    return {
      'status': 'ok',
      'result': response
    }