import os


def send_email_job(subject: str, body: str, to_list=None, attachments=None):
    os.environ["START_INLINE_WORKER"] = "0"
    from app import create_app
    from app.services.email_service import send_email

    app = create_app()
    with app.app_context():
        send_email(subject, body, to_list, attachments)
