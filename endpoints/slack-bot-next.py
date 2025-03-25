import json
import re
import traceback
from typing import Mapping
from werkzeug import Request, Response
from dify_plugin import Endpoint
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

class SlackEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Invokes the endpoint with the given request.
        """
        retry_num = r.headers.get("X-Slack-Retry-Num")
        if not settings.get("allow_retry") and (
            r.headers.get("X-Slack-Retry-Reason") == "http_timeout" or (retry_num is not None and int(retry_num) > 0)
        ):
            return Response(status=200, response="ok")
        
        data = r.get_json()

        # Handle Slack URL verification challenge
        if data.get("type") == "url_verification":
            return Response(
                response=json.dumps({"challenge": data.get("challenge")}),
                status=200,
                content_type="application/json"
            )

        
        if data.get("type") == "event_callback":
            event = data.get("event")
            
            # Bot自身の投稿は無視する（無限ループ防止）
            if event.get("bot_id") is not None:
                return Response(status=200, response="ok")
            
            channel = event.get("channel", "")
            blocks = event.get("blocks", [])
            message = ""
            process_event = False

            # チャンネルでのアプリメンションの場合
            if event.get("type") == "app_mention":
                message = event.get("text", "")
                # 正規表現でメンション部分を除去
                message = re.sub(r"<@\w+>", "", message).strip()
                # 参考コードのブロック編集処理を試みる
                if blocks and isinstance(blocks, list) and len(blocks) > 0:
                    try:
                        if blocks[0].get("elements") and isinstance(blocks[0]["elements"], list) and len(blocks[0]["elements"]) > 0:
                            first_elem = blocks[0]["elements"][0]
                            if first_elem.get("elements") and isinstance(first_elem["elements"], list) and len(first_elem["elements"]) > 1:
                                # 先頭の要素（メンション部分）を除去
                                first_elem["elements"] = first_elem["elements"][1:]
                    except Exception:
                        pass
                process_event = True

            # DMの場合：イベントタイプが"message"かつチャネルタイプが"im"
            elif event.get("type") == "message" and event.get("channel_type") == "im":
                message = event.get("text", "")
                process_event = True

            if process_event and message:
                token = settings.get("bot_token")
                client = WebClient(token=token)
                try:
                    response_data = self.session.app.chat.invoke(
                        app_id=settings["app"]["app_id"],
                        query=message,
                        inputs={},
                        response_mode="blocking",
                    )
                    answer = response_data.get("answer", "")
                    
                    # Slackへの返信内容を準備
                    post_kwargs = {
                        "channel": channel,
                        "text": answer
                    }
                    if blocks and isinstance(blocks, list) and len(blocks) > 0:
                        try:
                            if blocks[0].get("elements") and blocks[0]["elements"][0].get("elements"):
                                blocks[0]["elements"][0]["elements"][0]["text"] = answer
                                post_kwargs["blocks"] = blocks
                        except Exception:
                            pass
                    result = client.chat_postMessage(**post_kwargs)
                    return Response(
                        status=200,
                        response=json.dumps(result),
                        content_type="application/json"
                    )
                except SlackApiError as e:
                    return Response(
                        status=200,
                        response="Slack API Error: " + str(e),
                        content_type="text/plain"
                    )
                except Exception as e:
                    err = traceback.format_exc()
                    return Response(
                        status=200,
                        response="Sorry, I'm having trouble processing your request. Please try again later. " + str(err),
                        content_type="text/plain",
                    )
            else:
                return Response(status=200, response="ok")
        else:
            return Response(status=200, response="ok")
