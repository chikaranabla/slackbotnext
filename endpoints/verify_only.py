# endpoints/verify_only.py
import json
import logging
from typing import Mapping
from werkzeug import Request, Response
from dify_plugin import Endpoint

# ログ設定 (Dify Cloudでログが見れる場合に役立ちます)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - VerifyOnly - %(message)s')

class VerifyOnlyEndpoint(Endpoint):
    """
    Slack URL検証のみを行う最小限のエンドポイントクラス
    """
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        logging.info(f"Request received. Method: {r.method}, Path: {r.path}")
        logging.info(f"Headers: {r.headers}")

        # リクエストボディを取得
        request_body_raw = r.get_data(as_text=True)
        logging.info(f"Raw Request Body: {request_body_raw}")

        # ボディが空でないか確認
        if not request_body_raw:
            logging.warning("Request body is empty.")
            # Slackはボディが空のリクエストを送らないはずだが念のため
            return Response(status=400, response="Bad Request: Empty body")

        # JSONデコードを試みる
        data = None
        try:
            data = json.loads(request_body_raw)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode JSON request body: {e}")
            # 不正なJSONの場合は 400 Bad Request
            return Response(status=400, response="Bad Request: Invalid JSON")

        # --- ここからがURL検証の核心 ---
        # リクエストタイプが 'url_verification' かチェック
        if data and data.get("type") == "url_verification":
            challenge_value = data.get("challenge")
            logging.info(f"URL Verification type detected. Challenge value: {challenge_value}")

            # 'challenge' パラメータが存在するかチェック
            if challenge_value:
                # challenge値をJSON形式で返す
                response_body = json.dumps({"challenge": challenge_value})
                logging.info(f"Responding with challenge: {response_body}")
                return Response(
                    response=response_body,
                    status=200,
                    content_type="application/json"
                )
            else:
                # challenge値が見つからない場合はエラー
                logging.warning("Challenge parameter is missing in url_verification request.")
                return Response(status=400, response="Bad Request: Missing 'challenge' parameter")
        else:
            # URL検証以外のリクエストの場合
            request_type = data.get("type") if data else "Unknown or Not JSON"
            logging.info(f"Ignoring non-verification request. Type: {request_type}")
            # Slackの他のイベント等はこのテストでは無視し、単純にOKを返す
            return Response(status=200, response="ok, ignored (not url_verification)")
        # --- URL検証ここまで ---