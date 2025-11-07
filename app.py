from flask import Flask, request, Response
import requests
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__)

# 修改开关：True启用修改，False禁用修改
ENABLE_MODIFICATION = True
# M3U8代理前缀
M3U8_PROXY_PREFIX = "https://cfrp.996855.xyz/"

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
        
        content_type = resp.headers.get('content-type', '').lower()
        
        # M3U8文件特殊处理
        if is_m3u8_file(actual_url_str, content_type):
            return handle_m3u8_rewrite(resp, actual_url_str, url)
        
        # 当修改开关开启且是HTML内容时进行DOM重写
        if ENABLE_MODIFICATION and 'text/html' in content_type:
            return handle_html_rewrite(resp, url)
        
        # 返回原始响应
        response_headers = [(name, value) for name, value in resp.headers.items()]
        return Response(resp.content, status=resp.status_code, headers=response_headers)
        
    except Exception as error:
        return f"请求失败: {str(error)}", 500

def is_m3u8_file(url, content_type):
    """检查是否为M3U8文件"""
    # 通过URL后缀判断
    if url.lower().endswith(('.m3u8', '.m3u')):
        return True
    
    # 通过Content-Type判断
    m3u8_content_types = [
        'application/vnd.apple.mpegurl',
        'application/x-mpegurl',
        'audio/mpegurl',
        'audio/x-mpegurl'
    ]
    
    if any(m3u8_type in content_type for m3u8_type in m3u8_content_types):
        return True
    
    # 通过文件内容的前几个字符判断（如果是文本内容）
    return False

def handle_m3u8_rewrite(response, target_url, original_url):
    """处理M3U8文件重写，修改其中的URL"""
    try:
        content = response.text
        base_url = get_base_url(target_url)
        mirror_base = f"{request.scheme}://{request.host}"
        
        def rewrite_m3u8_line(line):
            """重写M3U8文件中的每一行"""
            line = line.strip()
            
            # 跳过注释和空行
            if not line or line.startswith('#'):
                return line
            
            # 处理TS文件路径和其他资源路径
            if not line.startswith(('http://', 'https://', '//')):
                # 相对路径，转换为绝对路径
                if line.startswith('/'):
                    # 绝对路径
                    parsed_base = urlparse(base_url)
                    absolute_url = f"{parsed_base.scheme}://{parsed_base.netloc}{line}"
                else:
                    # 相对路径
                    absolute_url = urljoin(base_url, line)
                
                # 添加代理前缀
                return f"{mirror_base}/{M3U8_PROXY_PREFIX}{absolute_url}"
            else:
                # 已经是绝对路径，直接添加代理前缀
                if line.startswith('//'):
                    line = f"https:{line}"  # 将协议相对URL转换为绝对URL
                return f"{mirror_base}/{M3U8_PROXY_PREFIX}{line}"
        
        # 处理M3U8内容
        lines = content.split('\n')
        rewritten_lines = []
        
        for line in lines:
            if line.strip().startswith('#EXT-X-STREAM-INF') or line.strip().startswith('#EXT-X-MEDIA'):
                # 处理流信息行，下一行通常是URL
                rewritten_lines.append(line)
            elif line.strip() and not line.strip().startswith('#'):
                # 处理URL行
                rewritten_lines.append(rewrite_m3u8_line(line))
            else:
                # 注释行或其他行保持不变
                rewritten_lines.append(line)
        
        rewritten_content = '\n'.join(rewritten_lines)
        
        # 设置正确的Content-Type
        headers = dict(response.headers)
        headers['Content-Type'] = 'application/vnd.apple.mpegurl'
        headers['Access-Control-Allow-Origin'] = '*'
        headers['Access-Control-Allow-Headers'] = '*'
        
        # 移除可能阻止播放的安全策略
        headers_to_remove = ['content-security-policy', 'Content-Security-Policy', 'X-Content-Type-Options']
        for header in headers_to_remove:
            if header in headers:
                del headers[header]
        
        return Response(rewritten_content, status=response.status_code, headers=headers)
        
    except Exception as e:
        # 如果处理失败，返回原始内容
        return Response(response.content, status=response.status_code, headers=dict(response.headers))

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

def get_base_url(url):
    """从URL获取基础路径"""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{'/'.join(parsed.path.split('/')[:-1])}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
