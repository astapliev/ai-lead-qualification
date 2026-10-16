"""Run the local form with a small, persistent worker thread pool."""
import os
from waitress import serve
from app import app

if __name__ == '__main__':
    serve(app, host='127.0.0.1', port=int(os.getenv('PORT', '5050')), threads=4,
          max_request_body_size=32 * 1024)
