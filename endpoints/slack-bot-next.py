# endpoints/slack-bot-next.py (一時的な検証用コード)
import json
import logging
from typing import Mapping
from werkzeug import Request, Response
from dify_plugin import Endpoint

# 簡単なログ設定 (Dify Cloud上でログが見れるかは不明ですが念のため)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SlackEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        logger.info(f"Received request: Headers={r.headers}, Body={r.data}") # リクエスト内容をログ出力試行

        try:
            # application/json の場合のみ get_json() を試す
            if r.content_type == 'application/json':
                data = r.get_json()
                logger.info(f"Parsed JSON data: {data}")

                if data and data.get("type") == "url_verification":
                    challenge = data.get("challenge")
                    logger.info(f"URL verification requested. Challenge: {challenge}")
                    if challenge:
                        response_body = json.dumps({"challenge": challenge})
                        logger.info(f"Responding with challenge: {response_body}")
                        return Response(
                            response=response_body,
                            status=200,
                            content_type="application/json"
                        )
                    else:
                        logger.warning("Missing challenge parameter in url_verification.")
                        return Response("Missing challenge", status=400)
                else:
                    logger.info("Request is not url_verification or data is missing.")
                    # 検証以外のリクエストは一旦無視
                    return Response("OK - Not URL Verification", status=200)
            else:
                # Slackの検証リクエストは通常JSONだが、それ以外の場合
                logger.warning(f"Received non-JSON request or unexpected content type: {r.content_type}")
                return Response("OK - Non-JSON or ignored", status=200)

        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            return Response(f"Internal Server Error: {e}", status=500)
