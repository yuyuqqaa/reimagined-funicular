from flask import Flask, request, Response
import requests
from urllib.parse import urljoin
import re

app = Flask(__name__)

# 修改开关：True启用修改，False禁用修改
ENABLE_MODIFICATION = True

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def proxy(path):
    url = request.url
    
    if not path:
        return "请输入 / 后面的链接", 400
    
    # 构建目标URL
    target_url_str = path + ('?' + request.query_string.decode() if request.query_string else '')
    
    # 检查是否包含协议
    has_protocol = target_url_str.startswith(('http://', 'https://'))
    
    if not has_protocol:
        actual_url_str = detect_protocol(target_url_str)
    else:
        actual_url_str = target_url_str
    
    try:
        # 创建请求到目标网站
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        resp = requests.request(
            method=request.method,
            url=actual_url_str,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True,
            stream=True
        )
        
        # 当修改开关开启且是HTML内容时进行DOM重写
        if ENABLE_MODIFICATION and 'text/html' in resp.headers.get('content-type', ''):
            return handle_html_rewrite(resp, url)
        
        # 返回原始响应
        response_headers = [(name, value) for name, value in resp.headers.items()]
        return Response(resp.content, status=resp.status_code, headers=response_headers)
        
    except Exception as error:
        return f"请求失败: {str(error)}", 500

def detect_protocol(domain):
    """检测使用HTTP还是HTTPS协议"""
    try:
        https_url = f"https://{domain}"
        response = requests.head(https_url, allow_redirects=False, timeout=5)
        if response.status_code < 400:
            return https_url
    except:
        pass
    return f"http://{domain}"

def handle_html_rewrite(response, original_url):
    """处理HTML重写，修改相对链接"""
    text = response.text
    mirror_base = f"{request.scheme}://{request.host}{request.path}"
    
    # 替换相对链接为绝对链接
    def replace_relative_links(match):
        prefix = match.group(1)
        path = match.group(2)
        # 如果路径已经是绝对路径或包含协议，则不替换
        if path.startswith(('http://', 'https://', '//')):
            return match.group(0)
        # 确保路径不以斜杠开头
        if path.startswith('/'):
            path = path[1:]
        return f'{prefix}{mirror_base}/{path}'
    
    # 使用正则表达式替换链接
    modified_text = re.sub(
        r'(<a[^>]+href=["\'])(?!https?://)([^"\']+)',
        replace_relative_links,
        text,
        flags=re.IGNORECASE
    )
    
    modified_text = re.sub(
        r'(<img[^>]+src=["\'])(?!https?://)([^"\']+)',
        replace_relative_links,
        modified_text,
        flags=re.IGNORECASE
    )
    
    # 移除可能阻止资源加载的安全策略头
    headers = dict(response.headers)
    headers_to_remove = ['content-security-policy', 'Content-Security-Policy']
    for header in headers_to_remove:
        if header in headers:
            del headers[header]
    
    return Response(modified_text, status=response.status_code, headers=headers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
