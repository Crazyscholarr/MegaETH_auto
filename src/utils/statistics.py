from tabulate import tabulate
from loguru import logger
import pandas as pd
from datetime import datetime
import os

from src.utils.config import Config, WalletInfo


def print_wallets_stats(config: Config, excel_path="data/progress.xlsx"):
    """
    In thống kê cho tất cả ví dưới dạng bảng và lưu vào tệp Excel

    Args:
        config: Cấu hình chứa dữ liệu ví
        excel_path: Đường dẫn để lưu tệp Excel (mặc định là "data/progress.xlsx")
    """
    try:
        # Sắp xếp ví theo chỉ số
        sorted_wallets = sorted(config.WALLETS.wallets, key=lambda x: x.account_index)

        # Chuẩn bị dữ liệu cho bảng
        table_data = []
        total_balance = 0
        total_transactions = 0

        for wallet in sorted_wallets:
            # Che giấu khóa riêng (5 ký tự cuối)
            masked_key = "•" * 3 + wallet.private_key[-5:]

            total_balance += wallet.balance
            total_transactions += wallet.transactions

            row = [
                str(wallet.account_index),  # Chỉ số không có số 0 dẫn đầu
                wallet.address,  # Địa chỉ đầy đủ
                masked_key,
                f"{wallet.balance:.8f} ETH",
                f"{wallet.transactions:,}",  # Định dạng số với dấu phân cách
            ]
            table_data.append(row)

        # Nếu có dữ liệu - in bảng và thống kê
        if table_data:
            # Tạo tiêu đề cho bảng
            headers = [
                "Số tài khoản",
                "Địa chỉ ví",
                "Khóa riêng",
                "Số dư (ETH)",
                "Tổng giao dịch",
            ]

            # Tạo bảng với định dạng cải tiến
            table = tabulate(
                table_data,
                headers=headers,
                tablefmt="double_grid",  # Viền đẹp hơn
                stralign="center",  # Căn giữa chuỗi
                numalign="center",  # Căn giữa số
            )

            # Tính giá trị trung bình
            wallets_count = len(sorted_wallets)
            avg_balance = total_balance / wallets_count
            avg_transactions = total_transactions / wallets_count

            # In bảng và thống kê
            logger.info(
                f"\n{'='*50}\n"
                f"         Thống kê ví ({wallets_count} ví)\n"
                f"{'='*50}\n"
                f"{table}\n"
                f"{'='*50}\n"
                f"{'='*50}"
            )

            logger.info(f"Số dư trung bình: {avg_balance:.8f} ETH")
            logger.info(f"Giao dịch trung bình: {avg_transactions:.1f}")
            logger.info(f"Tổng số dư: {total_balance:.8f} ETH")
            logger.info(f"Tổng giao dịch: {total_transactions:,}")

            # Xuất ra Excel
            # Tạo DataFrame cho Excel
            df = pd.DataFrame(table_data, columns=headers)

            # Thêm thống kê tổng hợp
            summary_data = [
                ["", "", "", "", ""],
                ["TỔNG HỢP", "", "", "", ""],
                [
                    "Tổng",
                    f"{wallets_count} ví",
                    "",
                    f"{total_balance:.8f} ETH",
                    f"{total_transactions:,}",
                ],
                [
                    "Trung bình",
                    "",
                    "",
                    f"{avg_balance:.8f} ETH",
                    f"{avg_transactions:.1f}",
                ],
            ]
            summary_df = pd.DataFrame(summary_data, columns=headers)
            df = pd.concat([df, summary_df], ignore_index=True)

            # Tạo thư mục nếu chưa tồn tại
            os.makedirs(os.path.dirname(excel_path), exist_ok=True)

            # Tạo tên tệp với ngày giờ
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"progress_{timestamp}.xlsx"
            file_path = os.path.join(os.path.dirname(excel_path), filename)

            # Lưu vào Excel
            df.to_excel(file_path, index=False)
            logger.info(f"Thống kê đã được xuất ra {file_path}")
        else:
            logger.info("\nKhông có thống kê ví nào khả dụng")

    except Exception as e:
        logger.error(f"Lỗi khi in thống kê: {e}")