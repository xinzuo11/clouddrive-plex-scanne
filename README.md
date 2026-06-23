# clouddrive-plex-scanne
clouddrive-plex-scanne的教程r，通过 Webhook 接收 CloudDrive 的文件变更通知，自动触发 Plex 局部扫描，需要 CloudDrive2 会员，除了直接在 CD2 内操作的变更，也支持三方应用调用 CD2 触发的文件变更
compose: onfig.ini需要是文件，logs文件夹
services:
  clouddrive-plex-scanner:
    image: clouddrive-plex-scanner:latest
    container_name: clouddrive-plex-scanner
    ports:
      - "5001:5001"
    volumes:
      - ./config.ini:/app/config.ini
      - ./logs:/app/logs
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
之后需要在CloudDrive中写webhook，需要将base_url = "http://192.168.100.103:5001"，中的ip改成你自己的ip
# global variables
# {device_name} - The name of the device
# {user_name} - Current user name
# {version} - The version of the application

# global parameters
[global_params]
base_url = "http://192.168.100.103:5001"
enabled = true

[global_params.default_headers]
content-type = "application/json"
user-agent = "clouddrive2/{version}"

# File system watcher webhook configuration
[file_system_watcher]
url = "{base_url}/webhook/clouddrive"
method = "POST"
enabled = true
body = '''
{
    "device_name": "{device_name}",
    "user_name": "{user_name}",
    "version": "{version}",
    "event_category": "{event_category}",
    "event_name": "{event_name}",
    "event_time": "{event_time}",
    "send_time": "{send_time}",
    "data": [
            {
                "action": "{action}",
                "is_dir": "{is_dir}",
                "source_file": "{source_file}",
                "destination_file": "{destination_file}"
            }
    ]
}
'''

# mount point watcher configuration
[mount_point_watcher]
url = "{base_url}/webhook/clouddrive"
method = "POST"
enabled = false
body = '''
{
    "device_name": "{device_name}",
    "user_name": "{user_name}",
    "version": "{version}",
    "event_category": "{event_category}",
    "event_name": "{event_name}",
    "event_time": "{event_time}",
    "send_time": "{send_time}",
    "data": [
            {
                "action": "{action}",
                "mount_point": "{mount_point}",
                "status": "{status}",
                "reason": "{reason}"
            }
    ]
}
'''
