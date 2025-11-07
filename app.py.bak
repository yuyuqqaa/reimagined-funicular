from flask import Flask, request, Response
import requests
from urllib.parse import urljoin, urlparse
import re

ENABLE_MODIFICATION = True  # 修改开关：True启用修改，False禁用修改

app = Flask(__name__)

async def detect_protocol(domain):
    """检测域名支持的协议"""
    try:
        https_url = f"https://{domain}"
        response = requests.head(https_url, allow_redirects=False)
        if response.status_code < 400:
            return https_url
    except:
        pass
    return f"http://{domain}"

async def handle_html_rewrite(response_text, original_url):
    """处理HTML重写，修复相对路径"""
    mirror_base = f"{request.url_root.rstrip('/')}{request.path}"
    
    # 使用正则表达式替换相对路径
    # 替换a标签的href属性
    modified_text = re.sub(
        r'(<a[^>]+href=["\'])(?!https?://)([^"\']+)',
        lambda m: f"{m.group(1)}{mirror_base}/{m.group(2)}",
        response_text,
        flags=re.IGNORECASE
    )
    
    # 替换img标签的src属性
    modified_text = re.sub(
        r'(<img[^>]+src=["\'])(?!https?://)([^"\']+)',
        lambda m: f"{m.group(1)}{mirror_base}/{m.group(2)}",
        modified_text,
        flags=re.IGNORECASE
    )
    
    return modified_text

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
async def proxy(path):
    """主代理函数"""
    if not path:
        return "请输入 / 后面的链接", 400
    
    # 构建目标URL
    target_url_str = path
    if request.query_string:
        target_url_str += f"?{request.query_string.decode()}"
    
    has_protocol = target_url_str.startswith(('http://', 'https://'))
    
    # 处理协议检测
    if not has_protocol:
        actual_url_str = await detect_protocol(target_url_str)
    else:
        actual_url_str = target_url_str
    
    try:
        # 转发请求
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        response = requests.request(
            method=request.method,
            url=actual_url_str,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True
        )
        
        # 当修改开关开启且是HTML内容时进行DOM重写
        if ENABLE_MODIFICATION:
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                modified_content = await handle_html_rewrite(response.text, request.url)
                
                # 创建新的响应头，移除可能阻止资源加载的安全策略
                new_headers = dict(response.headers)
                if 'content-security-policy' in new_headers:
                    del new_headers['content-security-policy']
                
                return Response(
                    modified_content,
                    status=response.status_code,
                    headers=new_headers
                )
        
        # 直接返回原始响应
        return Response(
            response.content,
            status=response.status_code,
            headers=dict(response.headers)
        )
        
    except Exception as error:
        return f"请求失败: {str(error)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
