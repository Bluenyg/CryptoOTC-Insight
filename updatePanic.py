import requests

def update_news(object_id, tag, summary, analysis, content):
    """
    通用API调用函数

    :param object_id: 文档唯一标识，必传，来自于batchNews接口同名字段
    :param tag: 新闻标签：1-正向，2-中性，3-负向 非必传，四个内容字段必传一个，不然报错
    :param summary: 新闻摘要，非必传
    :param content: 新闻内容，非必传
    :return: comment 新闻评论，非必传
    """
    # 设置默认请求头
    default_headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Origin': 'null',
        'Proxy-Connection': 'keep-alive',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'Content-Type': 'application/json',
    }
    api_url = 'http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews'
    data = {
        "objectId":object_id,
        "tag":tag
    }
    if summary != "":
        data["summary"] = summary
    if analysis != "":
        data["analysis"] = analysis
    if content != "":
        data["content"] = content

    try:
        response = requests.request(
            method="POST",
            url=api_url,
            headers=default_headers,
            json=data,
            timeout=5,
            verify=True
        )

        # 尝试解析JSON响应
        try:
            response_data = response.json()
        except ValueError:
            response_data = response.text

        # 处理非200状态码
        if response.status_code != 200:
            return (response.status_code,
                    f"API请求失败 [{response.status_code}]：{response_data}")

        return (response.status_code, response_data)

    except requests.exceptions.RequestException as e:
        return (500, f"网络请求异常：{str(e)}")


# Note: json_data will not be serialized by requests
# exactly as it was in the original request.
# data = '{"text":"请介绍下酒的卖点",\n"openId":"greenaaaaaaaaa"}'.encode()


if __name__ == "__main__":

    # POST请求示例
    post_status, post_result = update_news(
        "68bbfcbd0a898c59397355d5",2,"债市波动加剧，“负反馈”压力再现？央行今日将开展4000亿元MLF操作","",""
    )
    print(post_status)
"""
    返回status不为200,就不是成功的。
"""


