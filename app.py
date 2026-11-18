"""
TracePic 실행 진입점
- 개발:  python app.py            (또는 flask --app app run --debug)
- 운영:  gunicorn -w 2 -b 127.0.0.1:5555 app:app   (Nginx 리버스 프록시 뒤)
"""
from tracepic import create_app

# FLASK_ENV 환경 변수(.env)에 따라 development / production 설정이 적용된다.
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555)
