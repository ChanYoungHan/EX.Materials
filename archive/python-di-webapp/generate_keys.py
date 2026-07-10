from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import os

def generate_key_pair(key_dir="keys", key_size=2048):
    """RSA 키 쌍을 생성하고 파일로 저장"""
    # 디렉토리 생성
    os.makedirs(key_dir, exist_ok=True)
    
    # RSA 키 쌍 생성
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size
    )
    
    # 비밀키를 PEM 형식으로 저장
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()  # 실제 서비스에서는 암호화 권장
    )
    
    # 공개키를 PEM 형식으로 저장
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    # 키를 파일로 저장
    private_key_path = os.path.join(key_dir, "private_key.pem")
    public_key_path = os.path.join(key_dir, "public_key.pem")
    
    with open(private_key_path, "wb") as f:
        f.write(private_pem)
    
    with open(public_key_path, "wb") as f:
        f.write(public_pem)
    
    print(f"RSA 키 쌍이 생성되었습니다:")
    print(f"비밀키: {private_key_path}")
    print(f"공개키: {public_key_path}")
    
    return private_key_path, public_key_path

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="RSA 키 쌍 생성 스크립트")
    parser.add_argument("-d", "--directory", default="keys", help="키를 저장할 디렉토리")
    parser.add_argument("-s", "--size", type=int, default=2048, help="RSA 키 크기 (비트)")
    
    args = parser.parse_args()
    
    generate_key_pair(args.directory, args.size)