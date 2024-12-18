from string import Template


class Constants:
    QUERIES = {
        "INSERT_USER_CATV_HISTORY": "INSERT INTO api_catv_history(user_id,wallet_address,token_address,source_depth, "
                                    "distribution_depth,transaction_limit,from_date,to_date,logged_time,token_type) "
                                    "VALUES('{}','{}','{}','{}','{}','{}','{}','{}','{}','{}');",
        "INSERT_USER_CATV_PATH_SEARCH": "INSERT INTO api_catv_path_history(user_id,address_from,address_to,depth, "
                                        "from_date,to_date,logged_time,token_type,min_tx_amount, "
                                        "limit_address_tx_count, token_address) "
                                        "VALUES('{}','{}','{}','{}','{}','{}','{}','{}','{}','{}','{}');",
        "CATV_USAGE_QUERY": "SELECT d::date, coalesce(searches, 0) from "
                            "generate_series((now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date, "
                            "now()::date at TIME ZONE '{0}', '1 day') as ts(d) left outer join ("
                            "select count(id) as searches, date_trunc('day', logged_time at TIME ZONE '{0}')::date "
                            "as tz_date from api_catv_history where logged_time at TIME ZONE '{0}' >= "
                            "(now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date and "
                            "user_id = '{2}' group by tz_date)"
                            "x(searches, tz_date) on ts.d = x.tz_date",
    }
    NETWORK_CHAIN_MAPPING_FOR_QUERY = {
        "LUNC": "terra",
        "KLAY": "klaytn",
        "BSC": "bsc",
        "BNB": "binance",
        "TRX": "tron",
        "EOS": "eos",
        "XLM": "stellar",
        "XRP": "ripple",
        "LTC": "litecoin",
        "BCH": "bitcash",
        "ADA": "cardano",
        "FTM": "fantom",
        "POL": "matic",
        "AVAX": "avalanche",
        "DOGE": "dogecoin",
        "ZEC": "zcash",
        "DASH": "dash",
        "ETH": "ethereum",
        "BTC": "bitcoin"
    }

    NETWORK_CHAIN_MAPPING_FOR_RESPONSE = {
        "LUNC": "cosmos",
        "KLAY": "ethereum",
        "BSC": "ethereum",
        "BNB": "binance",
        "TRX": "tron",
        "EOS": "eos",
        "XLM": "stellar",
        "XRP": "ripple",
        "BTC": "bitcoin",
        "LTC": "bitcoin",
        "BCH": "bitcoin",
        "ADA": "cardano",
        "FTM": "ethereum",
        "POL": "ethereum",
        "AVAX": "ethereum",
        "DOGE": "bitcoin",
        "ZEC": "bitcoin",
        "DASH": "bitcoin",
        "ETH": "ethereum"
    }

    GRAPHQL_CURRENCY_MAPPING = {
        "TRX": "TRX",
        "BNB": "BNB",
        "KLAY": "KLAY",
        "BSC": "BNB",
        "ETH": "ETH"
    }
    # "FTM": "FTM",
    # "POL": "MATIC",
    # "AVAX": "AVAX"
    CATV_API_RESPONSE = {
        "UNAUTHORIZED": {"status": False, "data": {
            "message": "Api key invalid or expired"}},
        "INTERNAL_SERVER_ERROR": {"status": False,
                                  "data": {"message": "Internal server error"}},
        "NO_DATA_FOUND": {"status": False,
                          "data": {"message": "Sorry, No data found for the provided wallet address."}},
        "REQUIRED_HEADERS_MISSING": {"status": False, "data": {
            "message": "Required headers are missing"}},
        "INSUFFICIENT_CREDIT": {"status": False,
                                "data": {"message": "Insufficient credit"}},
        "REQUEST_BODY_MISSING": {"status": False,
                                 "data": {"message": "Unable to parse body"}},
        "API_KEY_MISSING": {"status": False, "data": {"message": "Api key required"}}
    }
    CATV_API = {
        "SUPPORTED_NETWORKS": ['BTC', 'ETH', 'LTC', 'TRX',
                               'EOS', 'XLM', 'ADA', 'BNB', 'BCH', 'XRP', 'BSC', 'KLAY',
                               'DASH', 'DOGE', 'ZEC', 'FTM', 'POL', 'AVAX'],
        "QUORUM_CHAINS": ['XRP', 'XLM'],
        "UTXO_CHAINS": ['BTC', 'LTC', 'BCH', 'ADA', 'DASH', 'DOGE', 'ZEC'],
        "CATV_REPORT_TIMED_OUT": "The API request timed out due to extensive processing time."
                                " Please try again with a lower 'depth' or 'transaction_limit'.",
        "CATV_REPORT_SUCCESS": "CATV Report generated successfully.",
        "CATV_REPORT_FAILED": "CATV Report generation failed for the input wallet address. Please try again.",
        "DEFAULT_TOKEN_ADDRESS": "0x0000000000000000000000000000000000000000"
    }
    CATV_QUERY_TEMPLATES = {
        # Template for Ethereum and compatible chains (ETH, KLAY, BSC, FTM, POL, AVAX)
        "ETHEREUM_LIKE": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                        $currency
                    ) {
                        receiver { 
                            address annotation receiversCount sendersCount
                            amountOut amountIn balance
                            firstTxAt { time } lastTxAt { time }
                            type smartContract { contractType }
                        }
                        sender { 
                            address annotation type
                            amountOut amountIn balance
                            smartContract { contractType }
                        }
                        transaction { hash value }
                        transactions { timestamp txHash txValue amount height }
                        depth amount amount_usd: amount(in: USD)
                        currency { name symbol tokenId tokenType address }
                    }
                }
            }
        """),

        # Template for Bitcoin-like chains (BTC, BCH, LTC, DOGE, ZEC, DASH)
        "BITCOIN_LIKE": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { 
                            address annotation type
                            receiversCount sendersCount
                            firstTxAt { time } lastTxAt { time }
                        }
                        sender { 
                            address annotation type
                            firstTxAt { time } lastTxAt { time }
                        }
                        transaction { hash valueIn valueOut }
                        transactions { timestamp }
                        depth amount amount_usd: amount(in: USD)
                        currency { symbol }
                    }
                }
            }
        """),

        # Template for XRP and XLM
        "RIPPLE_STELLAR": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        $tags
                        receiver { 
                            address annotation receiversCount sendersCount
                            firstTransferAt { time } lastTransferAt { time }
                        }
                        sender { 
                            address annotation
                            firstTransferAt { time } lastTransferAt { time }
                        }
                        transaction { hash time { time } valueFrom valueTo }
                        depth amountFrom amountTo operation
                        currencyFrom { name symbol }
                        currencyTo { name symbol }
                    }
                }
            }
        """),

        # Template for Binance Chain and TRON
        "BINANCE_TRON": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                        $currency
                    ) {
                        receiver {
                            address annotation type receiversCount sendersCount
                            firstTxAt { time } lastTxAt { time }
                            amountOut amountIn balance
                        }
                        sender { address annotation type }
                        transaction { hash value time { time } }
                        depth amount amount_usd: amount(in: USD)
                        currency { name symbol tokenId tokenType }
                    }
                }
            }
        """),

        # Template for EOS
        "EOS": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { 
                            address annotation type receiversCount sendersCount
                            firstTxAt { time } lastTxAt { time }
                            amountOut amountIn balance
                        }
                        sender { address annotation type }
                        transaction { hash value time { time } }
                        depth amount amount_usd: amount(in: USD)
                        currency { name symbol tokenId tokenType }
                    }
                }
            }
        """),

        # Template for Cardano (ADA)
        "CARDANO": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { address annotation }
                        sender { address annotation }
                        transaction { hash valueIn valueOut }
                        transactions { timestamp }
                        depth amount amount_usd: amount(in: USD)
                        currency { symbol }
                    }
                }
            }
        """),

        # Template for Terra (LUNC)
        "TERRA": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { address annotation }
                        sender { address annotation }
                        transaction { hash value }
                        block { timestamp { time ( format: "%Y-%m-%d" ) } }
                        depth amount amount_usd: amount(in: USD)
                        currency { symbol }
                    }
                }
            }
        """)
    }

    CK_QUERY_TEMPLATES = {
        # Template for Ethereum and compatible chains (ETH, KLAY, BSC, FTM, POL, AVAX)
        "ETHEREUM_LIKE": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                        $currency
                    ) {
                        receiver { 
                            address annotation
                            type smartContract { contractType }
                        }
                        sender {
                            address annotation
                            type smartContract { contractType }
                        }
                        transaction { hash value }
                        transactions { timestamp }
                        depth amount amount_usd: amount(in: USD)
                        currency { name symbol tokenType address }
                    }
                }
            }
        """),

        # Template for Bitcoin-like chains (BTC, BCH, LTC, DOGE, ZEC, DASH)
        "BITCOIN_LIKE": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver {
                            address annotation
                        }
                        sender {
                            address annotation
                        }
                        transaction { hash valueIn valueOut }
                        transactions { timestamp }
                        depth amount amount_usd: amount(in: USD)
                        currency { symbol }
                    }
                }
            }
        """),

        # Template for XRP and XLM
        "RIPPLE_STELLAR": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        $tags
                        receiver { 
                            address annotation
                        }
                        sender { 
                            address annotation
                        }
                        transaction { hash time { time } valueFrom valueTo }
                        depth amountFrom amountTo
                        currencyFrom { name symbol }
                        currencyTo { name symbol }
                    }
                }
            }
        """),

        # Template for Binance Chain and TRON
        "BINANCE_TRON": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                        $currency
                    ) {
                        receiver { 
                            address annotation type
                        }
                        sender { 
                            address annotation type 
                        }
                        transaction { hash value time { time } }
                        depth amount amount_usd: amount(in: USD)
                        currency { name symbol tokenId tokenType }
                    }
                }
            }
        """),

        # Template for EOS
        "EOS": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { 
                            address annotation type 
                        }
                        sender { 
                            address annotation type 
                        }
                        transaction { hash value time { time } }
                        depth amount amount_usd: amount(in: USD)
                        currency { name symbol tokenId tokenType }
                    }
                }
            }
        """),

        # Template for Cardano (ADA)
        "CARDANO": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { address annotation }
                        sender { address annotation }
                        transaction { hash valueIn valueOut }
                        transactions { timestamp }
                        depth amount amount_usd: amount(in: USD)
                        currency { symbol }
                    }
                }
            }
        """),

        # Template for Terra (LUNC)
        "TERRA": Template("""
            query sentinel_query {
                $network {
                    coinpath(
                        options: { direction: $direction, asc: "depth", limit: $limit }
                        initialAddress: { is: "$address" }
                        depth: { lteq: $depth }
                        date: { since: "$from_time", till: "$till_time" }
                    ) {
                        receiver { address annotation }
                        sender { address annotation }
                        transaction { hash value }
                        block { timestamp { time ( format: "%Y-%m-%d" ) } }
                        depth amount amount_usd: amount(in: USD)
                        currency { symbol }
                    }
                }
            }
        """)
    }

    # Mapping to determine which template to use for each chain
    CHAIN_TEMPLATE_MAPPING = {
        "ETH": "ETHEREUM_LIKE",
        "KLAY": "ETHEREUM_LIKE",
        "BSC": "ETHEREUM_LIKE",
        "FTM": "ETHEREUM_LIKE",
        "POL": "ETHEREUM_LIKE",
        "AVAX": "ETHEREUM_LIKE",
        "BTC": "BITCOIN_LIKE",
        "BCH": "BITCOIN_LIKE",
        "LTC": "BITCOIN_LIKE",
        "DOGE": "BITCOIN_LIKE",
        "ZEC": "BITCOIN_LIKE",
        "DASH": "BITCOIN_LIKE",
        "XRP": "RIPPLE_STELLAR",
        "XLM": "RIPPLE_STELLAR",
        "BNB": "BINANCE_TRON",
        "TRX": "BINANCE_TRON",
        "EOS": "EOS",
        "ADA": "CARDANO",
        "LUNC": "TERRA"
    }
