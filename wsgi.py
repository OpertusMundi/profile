# #!/usr/bin/env python
import os
import logging

from geoprofile.app import app

if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO)

    ssl_context = None
    port = 5000

    tls_cert = os.environ.get('TLS_CERTIFICATE')
    tls_key = os.environ.get('TLS_KEY')
    if tls_cert and tls_key:
        ssl_context = (tls_cert, tls_key)
        port = 5443

    app.run(host="0.0.0.0", port=port, ssl_context=ssl_context)
