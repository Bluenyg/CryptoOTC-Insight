import json

import requests

def api_call():
    headers = {
    'Content-Type': 'application/json',
    }
    #BTC_NEWS("BTC", 1),
    #ETH_NEWS("ETH", 2);
    #startTime 和endTime 最好不要差太多，必传

    json_data = {
        "type": 2,
        "startTime": "2025-11-30 24:00:00",
        "endTime": "2025-12-1 6:00:00"
    }

    response = requests.post('http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic', headers=headers, json=json_data)
    rsp = json.loads(response.text)


    ##
    ##{'_id': '{"$oid":"68a2dc923a3c83badca7ab50"}', 'objectId': '68a2dc923a3c83badca7ab50', 'time': '2025-08-14T13:04:38.000Z', 'link': 'https://www.binance.com/zh-CN/square/post/08-14-2025-eth-4-500-usdt-24-4-02-28306164832882', 'title': 'ETH 跌破 4,500 USDT，24 小时跌幅4.02%', 'content': '据币安行情数据显示，ETH 跌破 4,500 USDT，现报价 4,498.859863 USDT，24 小时跌幅4.02%。', 'type': 'market-news'}
    ## time : utc时间。link：新闻链接。title：标题。description：描述。type：消息类型
    print(rsp[0])
if __name__ == "__main__":

    # POST请求示例
    api_call()
    """
     {
     '_id': '{"$oid":"688304d89e85a02d2601c897"}',  ###忽略
     'objectId': '688304d89e85a02d2601c897',  ### 实体id，后续更新标记用这个作为输入参数
     'code': '000001',   ### 股票代码
     'date': '20250423', ### 日期
     'time': '202504230621',  ###具体时间
     'link': 'https://finance.sina.com.cn/jjxw/2025-04-23/doc-ineuawwa7121182.shtml', ### url 
     'title': '技术赋能 探索打造全国融媒改革新范式',  ### 标题
     'description': '',  ### 内容，有些内容是空的，应该是爬虫问题，我这边会先过滤掉空的数据
     'newsTag': 0,  ### 标志，1-正面 2-中性 3-负面
     'summary': None,  ### 摘要，ai可以生成一下
     'comment': None ### 评论，ai可以生成一下
     }
    """