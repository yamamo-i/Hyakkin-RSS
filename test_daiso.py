# ruff: noqa: S101
import pytest
import json
from unittest.mock import MagicMock, patch, mock_open
from bs4 import BeautifulSoup
import daiso

# テスト用データ
HTML_PAGINATION = """
<div class="pagination__nav">
    <a href="/collections/newarrival?page=1" data-page="1" class="pagination__nav-item link pagination__text" title="1ページへ">1</a>
    <span class="pagination__nav-item is-active pagination__text">2</span>
    <a href="/collections/newarrival?page=3" data-page="3" class="pagination__nav-item link pagination__text" title="3ページへ">3</a>
    <span class="pagination__nav-item  pagination__text">…</span>
    <a href="/collections/newarrival?page=24" data-page="24" class="pagination__nav-item link pagination__text" title="24ページへ">24</a>
</div>
"""

HTML_PRODUCT_LIST = """
<div class="product-list product-list--collection product-list--with-sidebar">
    <div class="product-item">
        <a class="product-item__title" href="/collections/newarrival/products/item1">
            商品A
        </a>
    </div>
    <div class="product-item">
        <a class="product-item__title" href="/collections/newarrival/products/item2">
            商品B
        </a>
    </div>
</div>
"""


def test_get_image_url():
    """画像URL生成のテスト"""
    src = "//example.com/image_{width}.jpg"
    result = daiso.get_image_url(src, 500)
    assert result == "https://example.com/image_500.jpg"


def test_get_last_page_with_pagination():
    """ページネーションがある場合の最終ページ取得テスト"""
    soup = BeautifulSoup(HTML_PAGINATION, "html.parser")
    assert daiso._get_last_page(soup) == 24


def test_get_last_page_no_pagination():
    """ページネーションがない（1ページのみ）場合のテスト"""
    soup = BeautifulSoup("<div></div>", "html.parser")
    assert daiso._get_last_page(soup) == 1


def test_parse_products_from_page():
    """商品情報のパーステスト"""
    soup = BeautifulSoup(HTML_PRODUCT_LIST, "html.parser")
    products = daiso._parse_products_from_page(soup)

    assert len(products) == 2
    assert products[0]["title"] == "商品A"
    assert products[0]["link"] == "https://jp.daisonet.com/collections/newarrival/products/item1"
    assert products[1]["title"] == "商品B"


def test_generate_rss():
    """RSS生成のテスト"""
    products = [{"title": "New Item", "link": "http://example.com/new"}]
    exist_products = {"New Item": "Wed, 01 Jan 2025 00:00:00 +0900"}

    rss = daiso.generate_rss(products, exist_products)

    assert "<title>New Item</title>" in rss
    assert "<link>http://example.com/new</link>" in rss
    # 既存の日付が使われているか確認
    assert "<pubDate>Wed, 01 Jan 2025 00:00:00 +0900</pubDate>" in rss


def test_get_exist_titles():
    """既存RSS読み込みのテスト"""
    xml_content = """
    <rss>
        <channel>
            <item>
                <title>Existing Item</title>
                <pubDate>Tue, 31 Dec 2024 00:00:00 +0900</pubDate>
            </item>
        </channel>
    </rss>
    """
    with patch("builtins.open", mock_open(read_data=xml_content)):
        with patch("os.path.exists", return_value=True):
            titles = daiso.get_exist_titles("dummy.xml")
            assert "Existing Item" in titles
            assert titles["Existing Item"] == "Tue, 31 Dec 2024 00:00:00 +0900"


def test_load_history_json():
    """JSON履歴読み込みのテスト"""
    history_data = {"Item A": "Date A"}
    with patch("builtins.open", mock_open(read_data=json.dumps(history_data))):
        with patch("daiso.path.exists", side_effect=lambda p: p.endswith(".json")):
            result = daiso.load_history("history.json", "dummy.xml")
            assert result == history_data


def test_load_history_fallback_xml():
    """JSONがなくXMLがある場合のフォールバックテスト"""
    xml_content = """<rss><channel><item><title>Item B</title><pubDate>Date B</pubDate></item></channel></rss>"""
    # path.exists: json -> False, xml -> True
    with patch("daiso.path.exists", side_effect=lambda p: p.endswith(".xml")):
        with patch("builtins.open", mock_open(read_data=xml_content)):
            result = daiso.load_history("history.json", "dummy.xml")
            assert "Item B" in result
            assert result["Item B"] == "Date B"


@pytest.mark.asyncio
async def test_fetch_new_arrivals():
    """非同期スクレイピングのテスト"""

    # 1ページ目のレスポンス（全2ページと仮定）
    mock_resp_p1 = MagicMock()
    mock_resp_p1.status_code = 200
    # data-page="24" を "2" に書き換えてテスト時間を短縮
    pagination_short = HTML_PAGINATION.replace('data-page="24"', 'data-page="2"')
    mock_resp_p1.text = pagination_short + HTML_PRODUCT_LIST

    # 2ページ目のレスポンス
    mock_resp_p2 = MagicMock()
    mock_resp_p2.status_code = 200
    # 商品名を変更して区別
    mock_resp_p2.text = HTML_PRODUCT_LIST.replace("商品A", "商品C").replace("商品B", "商品D")

    # requests.get をモック化
    with patch("daiso.requests.get") as mock_get:

        def side_effect(*args, **kwargs):
            url = args[0]
            # URLに応じてレスポンスを切り替え
            if "page=" not in url:
                return mock_resp_p1  # 1ページ目
            elif "page=2" in url:
                return mock_resp_p2  # 2ページ目
            return mock_resp_p1

        mock_get.side_effect = side_effect

        # 実行
        products = await daiso.fetch_new_arrivals()

        # 検証
        # 1ページ目(2件) + 2ページ目(2件) = 合計4件
        assert len(products) == 4

        titles = [p["title"] for p in products]
        assert "商品A" in titles
        assert "商品C" in titles

        # 呼び出し回数の確認 (1ページ目 + 2ページ目)
        assert mock_get.call_count == 2
