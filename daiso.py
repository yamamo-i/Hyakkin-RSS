import requests
import json
from bs4 import BeautifulSoup
import asyncio
import asyncclick as click
import logging
from datetime import datetime, timedelta, timezone
from os import path
from typing import List, Dict

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
JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST).strftime(DATE_FORMAT)


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


def _get_last_page(soup: BeautifulSoup) -> int:
    """
    ページネーションから最終ページ番号を取得します。

    :param soup: BeautifulSoupオブジェクト
    :return: 最終ページ番号
    """
    pagination_nav = soup.find("div", class_="pagination__nav")
    if not pagination_nav:
        return 1
    pages = pagination_nav.find_all("a", {"data-page": True})
    if not pages:
        return 1
    last_page = max(int(page["data-page"]) for page in pages)
    return last_page


def _parse_products_from_page(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    単一ページから商品情報を抽出します。

    :param soup: BeautifulSoupオブジェクト
    :return: 商品データのリスト
    """
    product_list = soup.find("div", class_="product-list product-list--collection product-list--with-sidebar")
    if not product_list:
        return []

    products = []
    for item in product_list.find_all("div", class_="product-item"):
        try:
            title_element = item.find("a", class_="product-item__title")
            if title_element:
                title = title_element.text.strip()
                link = f"https://jp.daisonet.com{title_element['href']}"
                logger.info(f"Found product: {title}")
                products.append({"title": title, "link": link})
        except (AttributeError, TypeError):
            logger.warning("Skipping an item due to missing information.")
            continue
    return products


async def fetch_new_arrivals() -> List[Dict[str, str]]:
    """
    DAISOの新着商品情報を全ページからスクレイピングして、商品データを抽出します。

    :return: 商品データのリスト(辞書型 {"title": 商品名, "link": 商品のURL})
    """
    all_products = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    loop = asyncio.get_running_loop()

    # First page to get pagination info
    logger.info("Fetching page 1 to determine total pages...")
    response = await loop.run_in_executor(None, lambda: requests.get(URL, headers=headers, timeout=60))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    last_page = _get_last_page(soup)
    logger.info(f"Total pages found: {last_page}")

    # Process first page
    logger.info("Processing page 1...")
    all_products.extend(_parse_products_from_page(soup))

    # Process remaining pages
    if last_page > 1:
        tasks = []
        sem = asyncio.Semaphore(5)

        async def _fetch_page(page_num: int):
            async with sem:
                logger.info(f"Fetching and processing page {page_num}...")
                page_url = f"{URL}?page={page_num}"
                try:
                    response = await loop.run_in_executor(None, lambda: requests.get(page_url, headers=headers, timeout=60))
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "html.parser")
                    return _parse_products_from_page(soup)
                except requests.RequestException as e:
                    logger.error(f"Could not fetch page {page_num}: {e}")
                    return []

        for page_num in range(2, last_page + 1):
            tasks.append(_fetch_page(page_num))

        results = await asyncio.gather(*tasks)
        for result in results:
            all_products.extend(result)

    return all_products


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


def load_history(history_path: str, xml_path: str) -> Dict[str, str]:
    """
    履歴ファイル(JSON)から過去の商品データを読み込みます。
    JSONがない場合は、既存のXMLファイルから読み込みを試みます。
    """
    if path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"履歴ファイルの読み込みに失敗しました: {e}")

    # Fallback to XML
    if path.exists(xml_path):
        logger.info("履歴ファイルが見つからないため、既存のRSSからデータを移行します。")
        return get_exist_titles(xml_path)

    return {}


def save_history(history_path: str, data: Dict[str, str]) -> None:
    """履歴データをJSONファイルに保存します。"""
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"履歴ファイルの保存に失敗しました: {e}")


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
        # 履歴ファイルのパスを出力ファイル名から生成 (例: docs/daiso_new_arrivals.xml -> docs/daiso_new_arrivals_history.json)
        history_path = path.splitext(output)[0] + "_history.json"

        logger.info("新着商品情報を取得中...")
        products = await fetch_new_arrivals()
        logger.info(f"{len(products)} 件の商品を取得しました。")

        # 過去のデータを読み込む
        exist_titles = load_history(history_path, output)
        logger.info(f"過去のデータから {len(exist_titles)} 件の商品タイトルを読み込みました。")

        # 新しい商品のみを抽出
        new_products = []
        for product in products:
            if product["title"] not in exist_titles:
                new_products.append(product)
                exist_titles[product["title"]] = NOW

        logger.info(f"{len(new_products)} 件の新しい商品が見つかりました。")

        logger.info("RSSファイルを生成中...")
        rss_content = generate_rss(new_products, exist_titles)

        with open(output, "w", encoding="utf-8") as file:
            file.write(rss_content)

        # 履歴を保存
        save_history(history_path, exist_titles)

        logger.info(f"RSSファイルを生成しました: {output}")
        logger.info(f"履歴ファイルを保存しました: {history_path}")
    except Exception:
        logger.exception("エラーが発生しました")


if __name__ == "__main__":
    asyncio.run(main())
