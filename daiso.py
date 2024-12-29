import requests
from bs4 import BeautifulSoup
import asyncio
import asyncclick as click
import logging
from datetime import datetime
from os import path

# ロガーの設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
    <channel>
        <title>DAISOの新着商品</title>
        <link>https://jp.daisonet.com/collections/newarrival</link>
        <description>DAISO 新着商品の一覧</description>
        <lastBuildDate>{lastBuildDate}</lastBuildDate>
        <language>ja</language>{items}
    </channel>
</rss>
"""

ITEM_TEMPLATE = """
        <item>
            <title>{title}</title>
            <link>{link}</link>
            <pubDate>{pubDate}</pubDate>
        </item>"""

URL = "https://jp.daisonet.com/collections/newarrival"
DATE_FORMAT = "%a, %d %b %Y %H:%M:%S +0900"
NOW = datetime.utcnow().strftime(DATE_FORMAT)


def get_image_url(data_src: str, width: int) -> str:
    """
    data-src属性から画像URLを生成する関数

    :param data_src: data-src属性の値
    :param width: 画像の幅（デフォルト400px）
    :return: 生成された画像URL
    """
    logger.debug(data_src)
    # //jp.daisonet.comが形式なのでhttps:を追加する
    return "https:" + data_src.format(width=width)


def fetch_new_arrivals() -> list:
    """
    DAISOの新着商品情報をスクレイピングして、商品データを抽出します。

    :return: 商品データのリスト(辞書型 {"title": 商品名, "link": 商品のURL})
    """
    response = requests.get(URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # 商品リストを抽出
    product_list = soup.find("div", class_="product-list product-list--collection product-list--with-sidebar")
    if not product_list:
        raise ValueError("商品リストが見つかりませんでした。")

    products = []
    for item in product_list.find_all("div", class_="product-item"):
        try:
            title = item.find("a", class_="product-item__title").text.strip()
            logger.info(f"title: {title}")
            link = f"https://jp.daisonet.com{item.find('a', class_='product-item__title')['href']}"
            products.append({"title": title, "link": link})
        except (AttributeError, TypeError):
            # 商品情報の一部が欠けている場合はスキップ
            continue

    return products


def generate_rss(products: list, exist_products: dict) -> str:
    """
    商品データを元にRSS形式のXMLを生成します。

    :param products: 商品データのリスト
    :param exist_products: 既存の商品データのリスト
    :return: RSS形式のXML
    """
    items = ""
    # formatted: Wed, 11 Jun 2008 15:30:59 +0900
    for product in products:
        # 既存の商品データに含まれている場合はmerge
        title = product["title"]
        items += ITEM_TEMPLATE.format(
            title=title,
            link=product["link"],
            pubDate=exist_products.get(title, NOW),
        )
    return RSS_TEMPLATE.format(lastBuildDate=NOW, items=items)


def get_exist_titles(xml_path: str) -> dict:
    """
    既存のRSSファイルから商品タイトルを取得します。
    """
    # 既存のファイルがあれば、商品タイトルを取得する
    if not path.exists(xml_path):
        return {}
    with open(xml_path, "r", encoding="utf-8") as file:
        # MEMO xmlをhtmlでparseしてwarningがでるが依存ライブラリ増やしたくないので一旦無視
        soup = BeautifulSoup(file, "html.parser")
        titles = {item.find("title").text: item.find("pubdate").text for item in soup.find_all("item")}
        return titles


@click.command()
@click.option(
    "--output",
    "-o",
    default="docs/daiso_new_arrivals.xml",
    help="生成したRSSファイルの出力先",
)
async def main(output: str) -> None:
    """
    DAISOの新着商品情報を取得して、RSS形式で出力します。
    """
    try:
        logger.info("新着商品情報を取得中...")
        # TODO: dailyで実行するので48件以上の商品がある場合は想定しないが、もし48件以上の商品がある場合はページネーションを考慮する
        products = fetch_new_arrivals()
        logger.info(f"{len(products)} 件の商品を取得しました。")

        # 既存のRSSファイルから商品タイトルを取得する
        exist_titles = get_exist_titles(output)
        logger.info(f"既存のRSSファイルから {len(exist_titles)} 件の商品タイトルを取得しました。")

        logger.info("RSSファイルを生成中...")
        rss_content = generate_rss(products, exist_titles)

        with open(output, "w", encoding="utf-8") as file:
            file.write(rss_content)

        logger.info(f"RSSファイルを生成しました: {output}")
    except Exception:
        logger.exception("エラーが発生しました")


if __name__ == "__main__":
    asyncio.run(main())
