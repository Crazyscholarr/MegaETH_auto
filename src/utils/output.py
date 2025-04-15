import os
from rich.console import Console
from rich.text import Text
from tabulate import tabulate
from rich.table import Table
from rich import box


def show_logo():
    
    # Xóa màn hình
    os.system("cls" if os.name == "nt" else "clear")

    console = Console()

    # Tạo bầu trời sao với logo được thiết kế
    logo_text = """

 ▄████▄   ██▀███   ▄▄▄      ▒███████▒▓██   ██▓  ██████  ▄████▄   ██░ ██  ▒█████   ██▓    ▄▄▄       ██▀███  
▒██▀ ▀█  ▓██ ▒ ██▒▒████▄    ▒ ▒ ▒ ▄▀░ ▒██  ██▒▒██    ▒ ▒██▀ ▀█  ▓██░ ██▒▒██▒  ██▒▓██▒   ▒████▄    ▓██ ▒ ██▒
▒▓█    ▄ ▓██ ░▄█ ▒▒██  ▀█▄  ░ ▒ ▄▀▒░   ▒██ ██░░ ▓██▄   ▒▓█    ▄ ▒██▀▀██░▒██░  ██▒▒██░   ▒██  ▀█▄  ▓██ ░▄█ ▒
▒▓▓▄ ▄██▒▒██▀▀█▄  ░██▄▄▄▄██   ▄▀▒   ░  ░ ▐██▓░  ▒   ██▒▒▓▓▄ ▄██▒░▓█ ░██ ▒██   ██░▒██░   ░██▄▄▄▄██ ▒██▀▀█▄  
▒ ▓███▀ ░░██▓ ▒██▒ ▓█   ▓██▒▒███████▒  ░ ██▒▓░▒██████▒▒▒ ▓███▀ ░░▓█▒░██▓░ ████▓▒░░██████▒▓█   ▓██▒░██▓ ▒██▒
░ ░▒ ▒  ░░ ▒▓ ░▒▓░ ▒▒   ▓▒█░░▒▒ ▓░▒░▒   ██▒▒▒ ▒ ▒▓▒ ▒ ░░ ░▒ ▒  ░ ▒ ░░▒░▒░ ▒░▒░▒░ ░ ▒░▓  ░▒▒   ▓▒█░░ ▒▓ ░▒▓░
  ░  ▒     ░▒ ░ ▒░  ▒   ▒▒ ░░░▒ ▒ ░ ▒ ▓██ ░▒░ ░ ░▒  ░ ░  ░  ▒    ▒ ░▒░ ░  ░ ▒ ▒░ ░ ░ ▒  ░ ▒   ▒▒ ░  ░▒ ░ ▒░
░          ░░   ░   ░   ▒   ░ ░ ░ ░ ░ ▒ ▒ ░░  ░  ░  ░  ░         ░  ░░ ░░ ░ ░ ▒    ░ ░    ░   ▒     ░░   ░ 
░ ░         ░           ░  ░  ░ ░     ░ ░           ░  ░ ░       ░  ░  ░    ░ ░      ░  ░     ░  ░   ░     
░                           ░         ░ ░              ░                                                   
"""

    # Tạo văn bản gradient
    gradient_logo = Text(logo_text)
    gradient_logo.stylize("bold bright_cyan")

    # Hiển thị với khoảng cách
    console.print(gradient_logo)
    print()


def show_dev_info():
    """Hiển thị thông tin phát triển và phiên bản"""
    console = Console()

    # Tạo bảng đẹp
    table = Table(
        show_header=False,
        box=box.DOUBLE,
        border_style="bright_cyan",
        pad_edge=False,
        width=85,
        highlight=True,
    )

    # Thêm cột
    table.add_column("Nội dung", style="bright_cyan", justify="center")

    # Thêm các dòng với thông tin liên hệ
    table.add_row("✨ MegaETH Bot 1.2 ✨")
    table.add_row("─" * 43)
    table.add_row("")
    table.add_row("⚡ GitHub: [link]https://github.com/Crazyscholarr[/link]")
    table.add_row("👤 Dev: [link]https://web.telegram.org/k/#@Crzscholar[/link]")
    table.add_row("💬 Chat: [link]https://web.telegram.org/k/#@dgpubchat[/link]")
    table.add_row(
        
    )
    table.add_row("")

    # Hiển thị bảng với khoảng cách
    print("   ", end="")
    print()
    console.print(table)
    print()