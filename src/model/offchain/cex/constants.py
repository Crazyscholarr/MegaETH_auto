CEX_WITHDRAWAL_RPCS = {
    "Arbitrum": "https://arb1.lava.build",
    "Optimism": "https://optimism.lava.build",
    "Base": "https://base.lava.build",
}

# Ánh xạ tên mạng cho các sàn giao dịch khác nhau
NETWORK_MAPPINGS = {
    "okx": {
        "Arbitrum": "ARBONE",
        "Base": "Base",
        "Optimism": "OPTIMISM"
    },
    "bitget": {
        "Arbitrum": "ARBONE",
        "Base": "BASE",
        "Optimism": "OPTIMISM"
    }
}

# Tham số cụ thể cho sàn giao dịch
EXCHANGE_PARAMS = {
    "okx": {
        "balance": {"type": "funding"},
        "withdraw": {"pwd": "-"}
    },
    "bitget": {
        "balance": {},
        "withdraw": {}
    }
}

# Các sàn giao dịch được hỗ trợ
SUPPORTED_EXCHANGES = ["okx", "bitget"]