# Hyakkin-RSS
100円均一の情報を配信するRSS XMLを生成するツール

## RSS

以下のURLで配信されているXMLをRSSクライアントとsubscribeしてください

| 店舗 | URL |
|-|-|
| DAISO | https://yamamo-i.github.io/Hyakkin-RSS/daiso_new_arrivals.xml |

## 技術的な話

### Usage

* install dependencies
  ```shell
  # 利用時
  pip install .
  # 開発時
  pip install '.[dev]'
  ```
* exec
  ``` shell
  python daiso.py ${output_file_path}
  ```
* help
  ```shell
  $ python daiso.py --help
    Usage: daiso.py [OPTIONS]

    DAISOの新着商品情報を取得して、RSS形式で出力します。

    Options:
    -o, --output TEXT  生成したRSSファイルの出力先
    --help             Show this message and exit.
  ```

### 配信方法
* GitHub Pagesを使って配信している
  * `/docs` 配下を自動連携
