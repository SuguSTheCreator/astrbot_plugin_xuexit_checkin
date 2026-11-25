"""通用 Webhook 推送：Server酱 / Bark / 自定义 URL。"""
import requests


def send_webhook(url, title, text, timeout=10.0):
    if not url:
        return False
    try:
        if "sctapi.ftqq.com" in url or "pushplus" in url:
            resp = requests.post(url, data={"title": title, "desp": text}, timeout=timeout)
        else:
            resp = requests.post(
                url,
                json={"title": title, "text": text, "content": text},
                timeout=timeout,
            )
        resp.raise_for_status()
        return True
    except requests.RequestException:
        return False
