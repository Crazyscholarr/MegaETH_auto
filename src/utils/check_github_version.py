import aiohttp
import os
from datetime import datetime, timezone
import time
from typing import Tuple


async def get_github_last_commit(
    repo_owner: str, repo_name: str
) -> Tuple[str, str, str]:
    """
    Lấy thông tin commit mới nhất từ GitHub
    Trả về: (commit_hash, commit_date, commit_message)
    """
    async with aiohttp.ClientSession() as session:
        try:
            # Thêm headers để tránh giới hạn API và lấy dữ liệu mới
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "If-None-Match": "",  # Bỏ qua cache
                "Cache-Control": "no-cache",
            }

            # Thử với nhánh main trước
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/main"
            async with session.get(url, headers=headers) as response:
                if response.status == 404:
                    # Nếu nhánh main không tồn tại, thử nhánh master
                    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/master"
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            return (
                                data["sha"][:7],
                                data["commit"]["author"]["date"],
                                data["commit"]["message"],
                            )
                elif response.status == 200:
                    data = await response.json()
                    return (
                        data["sha"][:7],
                        data["commit"]["author"]["date"],
                        data["commit"]["message"],
                    )

                print(f"Gỡ lỗi - Trạng thái API GitHub: {response.status}")  # In gỡ lỗi

            current_time = datetime.now(timezone.utc)
            print(f"Gỡ lỗi - Thời gian dự phòng: {current_time.isoformat()}")  # In gỡ lỗi
            return "unknown", current_time.isoformat(), "unknown"
        except Exception as e:
            print(f"❌ Lỗi khi lấy thông tin commit từ GitHub: {e}")
            current_time = datetime.now(timezone.utc)
            print(f"Gỡ lỗi - Thời gian dự phòng lỗi: {current_time.isoformat()}")  # In gỡ lỗi
            return "unknown", current_time.isoformat(), "unknown"


def get_local_commit_info() -> tuple[str, str]:
    """
    Lấy thông tin commit cục bộ
    Trả về: (commit_hash, commit_date)
    """
    try:
        version_file = os.path.join(os.path.dirname(__file__), "..", "version.txt")
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                content = f.read().strip().split(",")
                if len(content) == 2:
                    return content[0], content[1]
        return None, None
    except Exception as e:
        print(f"❌ Lỗi khi đọc phiên bản cục bộ: {e}")
        return None, None


async def compare_versions(
    local_date: str,
    github_date: str,
    local_hash: str,
    github_hash: str,
    commit_message: str,
) -> Tuple[bool, str]:
    """
    So sánh phiên bản cục bộ và GitHub bằng ngày commit
    Trả về: (is_latest, message)
    """
    try:
        # Định dạng ngày GitHub để hiển thị (luôn ở UTC)
        github_dt = datetime.fromisoformat(github_date.replace("Z", "+00:00"))
        formatted_date = github_dt.strftime("%d.%m.%Y %H:%M UTC")

        # Nếu hash trùng khớp, đây là phiên bản mới nhất
        if local_hash == github_hash:
            return (
                True,
                f"✅ Bạn đang sử dụng phiên bản mới nhất (commit từ {formatted_date})",
            )

        # Nếu hash khác nhau, cần cập nhật
        return (
            False,
            f"⚠️ Có bản cập nhật mới!\n"
            f"📅 Bản cập nhật mới nhất được phát hành: {formatted_date}\n"
            f"ℹ️ Để cập nhật, sử dụng: git pull\n"
            f"📥 Hoặc tải xuống từ: https://github.com/Crazyscholarr/MegaETH_auto",
        )

    except Exception as e:
        print(f"❌ Lỗi khi so sánh phiên bản: {e}")
        return False, "Lỗi khi so sánh phiên bản"


def save_current_version(commit_hash: str, commit_date: str) -> None:
    """
    Lưu thông tin phiên bản hiện tại vào version.txt
    """
    try:
        version_file = os.path.join(
            os.path.dirname(__file__), "..", "version.txt"
        )  # Đường dẫn tới version.txt
        with open(version_file, "w") as f:
            f.write(f"{commit_hash},{commit_date}")
    except Exception as e:
        print(f"❌ Lỗi khi lưu thông tin phiên bản: {e}")


async def check_version(repo_owner: str = "Crazyscholarr", repo_name: str = "MegaETH_auto") -> bool:
    """
    Hàm chính để kiểm tra phiên bản và in trạng thái
    """
    print("🔍 Đang kiểm tra phiên bản...")

    # Lấy thông tin commit mới nhất từ GitHub
    github_hash, github_date, commit_message = await get_github_last_commit(
        repo_owner, repo_name
    )

    # Lấy thông tin phiên bản cục bộ
    local_hash, local_date = get_local_commit_info()

    # Nếu là lần chạy đầu tiên
    if local_hash is None:
        save_current_version(github_hash, github_date)
        github_dt = datetime.fromisoformat(github_date.replace("Z", "+00:00"))
        formatted_date = github_dt.strftime("%d.%m.%Y %H:%M UTC")
        print(
            f"📥 Đang khởi tạo theo dõi phiên bản...\n"
            f"📅 Phiên bản hiện tại từ: {formatted_date} \n"
        )
        return True

    # So sánh phiên bản
    is_latest, message = await compare_versions(
        local_date, github_date, local_hash, github_hash, commit_message
    )
    print(message)

    # Nếu phiên bản khác nhau, cập nhật phiên bản cục bộ
    if not is_latest:
        save_current_version(github_hash, github_date)

    return is_latest