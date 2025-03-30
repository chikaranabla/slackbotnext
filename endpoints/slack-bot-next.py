import json
import re
import traceback
from typing import Mapping
from werkzeug import Request, Response
from dify_plugin import Endpoint
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging # logging モジュールをインポート

# ログ設定（モジュールのトップレベルで設定）
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SlackEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Invokes the endpoint with the given request.
        """
        # --- リクエスト受信ログ ---
        logging.info(f"Received request from {r.remote_addr}")
        logging.info(f"Headers: {r.headers}")
        request_body_raw = r.get_data(as_text=True)
        logging.info(f"Raw Body: {request_body_raw}")
        # --- ここまで ---

        data = None
        if request_body_raw:
            try:
                data = json.loads(request_body_raw)
            except json.JSONDecodeError as e:
                logging.error(f"Failed to decode JSON request body: {e}")
                # JSONデコード失敗時は 400 Bad Request を返すのが適切
                return Response(status=400, response="Bad Request: Invalid JSON")

        # --- ★最優先★ Slack URL検証チャレンジを処理する ---
        if data and data.get("type") == "url_verification":
            challenge_value = data.get("challenge")
            logging.info(f"URL Verification challenge received: {challenge_value}")
            if challenge_value:
                response_body = json.dumps({"challenge": challenge_value})
                logging.info(f"Responding to challenge with: {response_body}")
                return Response(
                    response=response_body,
                    status=200,
                    content_type="application/json"
                )
            else:
                logging.warning("URL Verification type received, but 'challenge' parameter missing.")
                return Response(status=400, response="Bad Request: Missing 'challenge' parameter for url_verification.")
        # --- ここまで URL検証 ---

        # --- リトライ処理 (URL検証の後！) ---
        # allow_retry設定がない場合やFalseの場合にリトライを無視する
        allow_retry = settings.get("allow_retry", False) # デフォルトはFalseとする
        retry_num = r.headers.get("X-Slack-Retry-Num")
        retry_reason = r.headers.get("X-Slack-Retry-Reason")

        if not allow_retry and (retry_reason == "http_timeout" or (retry_num is not None and int(retry_num) > 0)):
            logging.info(f"Ignoring Slack retry request (Num: {retry_num}, Reason: {retry_reason}) based on allow_retry={allow_retry}.")
            # Slackにはリトライを受け付けなかったことを示すために200 OKを返す
            return Response(status=200, response="ok, retry ignored")
        # --- ここまで リトライ処理 ---

        # --- イベントコールバック処理 ---
        if data and data.get("type") == "event_callback":
            event = data.get("event")
            if not event:
                logging.warning("event_callback received but 'event' field is missing.")
                return Response(status=200, response="ok, missing event field") # イベントがない場合

            event_type = event.get("type")
            logging.info(f"Processing event_callback. Event type: {event_type}, Channel: {event.get('channel')}, Channel Type: {event.get('channel_type')}")

            # Bot自身の投稿は無視する（無限ループ防止）
            if event.get("bot_id") is not None:
                logging.info("Ignoring event from bot itself (bot_id present).")
                return Response(status=200, response="ok, ignored bot message")

            channel = event.get("channel", "")
            message = ""
            process_event = False

            # チャンネルでのアプリメンションの場合
            if event_type == "app_mention":
                logging.info("Detected app_mention event.")
                raw_message = event.get("text", "")
                # メンション部分を除去（メンション後のスペースも考慮）
                message = re.sub(r"<@\w+>\s*", "", raw_message).strip()
                logging.info(f"Extracted message from app_mention: '{message}'")
                process_event = True if message else False # 空メッセージは処理しない

            # DMの場合：イベントタイプが"message"かつチャネルタイプが"im"
            elif event_type == "message" and event.get("channel_type") == "im":
                logging.info("Detected direct message (im) event.")
                message = event.get("text", "")
                # DMでも空メッセージは処理しない方が良い場合がある
                logging.info(f"Extracted message from DM: '{message}'")
                process_event = True if message else False

            if process_event:
                token = settings.get("bot_token")
                app_settings = settings.get("app") # app-selectorで設定された値

                # --- 設定値のチェック ---
                if not token:
                    logging.error("Bot token is missing in plugin settings.")
                    # 設定不備をユーザーに通知することもできるが、まずはログに記録
                    return Response(status=200, response="ok, missing bot token setting")
                if not app_settings or not app_settings.get("app_id"):
                    logging.error("Dify App ID is missing in plugin settings.")
                    # 設定不備をユーザーに通知
                    client = WebClient(token=token)
                    try:
                        client.chat_postMessage(channel=channel, text="Configuration Error: The target Dify App is not set correctly in the plugin settings.")
                    except SlackApiError as e:
                        logging.error(f"Failed to post configuration error message to Slack: {e.response['error']}")
                    return Response(status=200, response="ok, missing app_id setting")
                # --- 設定値チェックここまで ---

                client = WebClient(token=token)
                try:
                    dify_app_id = app_settings["app_id"]
                    logging.info(f"Invoking Dify App '{dify_app_id}' with query: '{message}'")

                    # Difyアプリ呼び出し
                    response_data = self.session.app.chat.invoke(
                        app_id=dify_app_id,
                        query=message,
                        inputs={}, # 必要に応じてinputsを設定
                        response_mode="blocking", # または "streaming"
                    )
                    answer = response_data.get("answer", "Sorry, I could not get a response from the App.")
                    logging.info(f"Received answer from Dify App: '{answer}'")

                    try:
                        # --- Slackへの応答 (シンプルテキスト) ---
                        logging.info(f"Sending text response to Slack channel {channel}")
                        result = client.chat_postMessage(
                            channel=channel,
                            text=answer
                        )
                        logging.info(f"Successfully posted message to Slack. Timestamp: {result.get('ts')}")
                        # Slack APIの応答をそのまま返す必要はない。成功したことを示すOKを返す。
                        return Response(status=200, response="ok, message sent")
                        # --- ここまでシンプルテキスト応答 ---

                    except SlackApiError as e:
                        # Slack API呼び出し時のエラー
                        logging.error(f"Slack API Error when posting message: {e.response['error']}")
                        # SlackにはOKを返し、エラーはログで確認
                        return Response(status=200, response="ok, slack api error posting message")

                except Exception as e:
                    # Difyアプリ呼び出しやその他の予期せぬエラー
                    error_details = traceback.format_exc()
                    logging.error(f"Error processing event: {e}\n{error_details}")
                    try:
                        # ユーザーに内部エラーを通知
                        client.chat_postMessage(channel=channel, text="Sorry, an internal error occurred while processing your request. Please contact the administrator.")
                    except SlackApiError as slack_err:
                        logging.error(f"Failed to post internal error message to Slack: {slack_err.response['error']}")
                    # SlackにはOKを返す
                    return Response(status=200, response="ok, internal server error")
            else:
                # 処理対象外のイベント（app_mention/DM以外、または空メッセージ）
                logging.info("Event received but no action taken (not app_mention/DM or empty message).")
                return Response(status=200, response="ok, no action needed")
        else:
            # event_callback, url_verification 以外のリクエストタイプ（または data が None）
            request_type = data.get("type") if data else "Unknown or No Data"
            logging.info(f"Ignoring request type: {request_type}")
            return Response(status=200, response="ok, ignored request type")