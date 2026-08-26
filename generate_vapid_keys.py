"""
產生一組新的 VAPID 金鑰（Web Push 推播用）。

用法：
    pip install cryptography
    python generate_vapid_keys.py

會印出 VAPID_PUBLIC_KEY 和 VAPID_PRIVATE_KEY 兩個環境變數的值，
把它們設定到 Render 的 Environment 裡就可以了。

⚠️ VAPID_PRIVATE_KEY 是機密資料，只能放在 Render 的環境變數裡，
千萬不要 commit 進 GitHub、不要貼在任何公開的地方。
"""

import base64

from cryptography.hazmat.primitives.asymmetric import ec


def generate_vapid_keys():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    public_numbers = public_key.public_numbers()
    x = public_numbers.x.to_bytes(32, "big")
    y = public_numbers.y.to_bytes(32, "big")
    uncompressed_point = b"\x04" + x + y
    public_b64 = base64.urlsafe_b64encode(uncompressed_point).rstrip(b"=").decode()

    private_value = private_key.private_numbers().private_value
    private_bytes = private_value.to_bytes(32, "big")
    private_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode()

    return public_b64, private_b64


if __name__ == "__main__":
    pub, priv = generate_vapid_keys()
    print("把下面兩行加到 Render 的 Environment：\n")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print("\nVAPID_CLAIM_EMAIL 隨便填一個你的信箱就可以，例如 VAPID_CLAIM_EMAIL=you@example.com")
