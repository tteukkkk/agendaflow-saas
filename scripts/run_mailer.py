"""Worker de e-mail simples, somente uma instância. Preferir orquestrador com backoff e métricas em produção."""
import time
from .mail_worker import send_queued


def main():
    while True:
        send_queued(limit=40)
        time.sleep(60)


if __name__ == '__main__':
    main()
