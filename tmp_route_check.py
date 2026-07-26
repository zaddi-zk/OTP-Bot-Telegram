from bot import app as flask_app
from live_listen.server import app as fastapi_app
from config import build_public_base_url, build_media_stream_url

flask_rules = [rule.rule for rule in flask_app.url_map.iter_rules() if rule.rule in {'/voice','/twilio/voice','/twilio/status','/twilio/recording','/amd_callback','/ai_start'}]
fastapi_paths = [route.path for route in fastapi_app.router.routes if getattr(route, 'path', None) in {'/twilio/media','/twilio/status','/audio/{call_sid}/{filename}','/health'}]
print('FLASK_ROUTES', flask_rules)
print('FASTAPI_ROUTES', fastapi_paths)
print('PUBLIC_BASE', build_public_base_url())
print('MEDIA_URL', build_media_stream_url())
