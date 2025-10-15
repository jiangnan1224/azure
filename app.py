import os, json, threading, string, random, base64, time, logging, uuid, sqlite3
from flask import Flask, render_template, jsonify, request, session, g, redirect, url_for
from functools import wraps
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError, HttpResponseError

app = Flask(__name__)
# 从环境变量获取密码，如果没有设置则使用默认值
PASSWORD = os.environ.get('AZURE_PANEL_PASSWORD', 'You22kme#12345')
# 使用 PASSWORD 来生成 secret_key，确保每次密码更改时 secret_key 也会更改
app.secret_key = f'azure_panel_{PASSWORD}_secret_key_{os.environ.get("SECRET_KEY_SALT", "default")}'
KEYS_FILE = os.path.join('data', 'azure_keys.json')
DATABASE = os.path.join('data', 'tasks.db')

# 配置日志输出到标准输出
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    if not os.path.exists(DATABASE):
        with app.app_context():
            db = get_db()
            schema_sql = "CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT NOT NULL, result TEXT);"
            db.cursor().executescript(schema_sql)
            db.commit()
            app.logger.info("Database initialized.")

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv
def load_keys():
    if not os.path.exists(KEYS_FILE): return []
    try:
        with open(KEYS_FILE, 'r') as f: content = f.read(); return json.loads(content) if content else []
    except json.JSONDecodeError: return []
def save_keys(keys):
    with open(KEYS_FILE, 'w') as f: json.dump(keys, f, indent=4)
def generate_password(length=12):
    characters = string.ascii_letters + string.digits + "!@#$%^&*()"
    return ''.join(random.choice(characters) for i in range(length))
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_logged_in" not in session:
            if request.path.startswith('/api/'): return jsonify({"error": "用户未登录"}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function
def azure_credentials_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'azure_credentials' not in session: return jsonify({"error": "请先选择一个Azure账户"}), 403
        g.azure_creds = session['azure_credentials']
        return f(*args, **kwargs)
    return decorated_function
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["user_logged_in"] = True; return redirect(url_for('index'))
        else:
            return render_template("login.html", error="密码错误")
    return render_template("login.html")
@app.route("/logout")
def logout():
    session.clear(); return redirect('/login')
@app.route("/")
@login_required
def index():
    return render_template("index.html")
@app.route("/api/accounts", methods=["GET", "POST"])
@login_required
def manage_accounts():
    if request.method == "GET": accounts = load_keys(); return jsonify(accounts)
    data = request.json; keys = load_keys()
    if any(k['name'] == data['name'] for k in keys): return jsonify({"error": "账户名称已存在"}), 400
    keys.append(data); save_keys(keys); return jsonify({"success": True}), 201
@app.route("/api/accounts/<name>", methods=["DELETE"])
@login_required
def delete_account(name):
    keys = load_keys(); keys_to_keep = [k for k in keys if k['name'] != name]
    if len(keys) == len(keys_to_keep): return jsonify({"error": "账户未找到"}), 404
    save_keys(keys_to_keep)
    if session.get('azure_credentials', {}).get('name') == name: session.pop('azure_credentials', None)
    return jsonify({"success": True})
@app.route('/api/accounts/edit', methods=['POST'])
@login_required
def edit_account():
    data = request.json; original_name, new_name, expiration_date = data.get('original_name'), data.get('new_name'), data.get('expiration_date')
    if not original_name or not new_name: return jsonify({"error": "账户名称不能为空"}), 400
    keys = load_keys(); account_to_edit = next((k for k in keys if k['name'] == original_name), None)
    if not account_to_edit: return jsonify({"error": "未找到原始账户"}), 404
    if new_name != original_name and any(k['name'] == new_name for k in keys): return jsonify({"error": "新的账户名称已存在"}), 400
    account_to_edit['name'] = new_name; account_to_edit['expiration_date'] = expiration_date; save_keys(keys)
    if session.get('azure_credentials', {}).get('name') == original_name:
        session['azure_credentials']['name'] = new_name; session['azure_credentials']['expiration_date'] = expiration_date
    return jsonify({"success": True})
@app.route("/api/session", methods=["POST", "DELETE", "GET"])
@login_required
def azure_session():
    if request.method == "POST":
        name = request.json.get("name"); account = next((k for k in load_keys() if k['name'] == name), None)
        if not account: return jsonify({"error": "账户未找到"}), 404
        session['azure_credentials'] = account; return jsonify({"success": True, "name": account['name']})
    if request.method == "DELETE": session.pop('azure_credentials', None); return jsonify({"success": True})
    if 'azure_credentials' in session: return jsonify({"logged_in": True, "name": session['azure_credentials']['name']})
    return jsonify({"logged_in": False})
@app.route('/api/vms')
@login_required
@azure_credentials_required
def get_vms():
    try:
        credential, subscription_id = ClientSecretCredential(**g.azure_creds), g.azure_creds['subscription_id']
        compute_client, network_client = ComputeManagementClient(credential, subscription_id), NetworkManagementClient(credential, subscription_id)
        vm_list = []
        for vm in compute_client.virtual_machines.list_all():
            resource_group = vm.id.split('/')[4]; instance_view = compute_client.virtual_machines.instance_view(resource_group, vm.name)
            status, public_ip = "Unknown", "N/A"; power_state = next((s for s in instance_view.statuses if s.code.startswith('PowerState/')), None)
            if power_state: status = power_state.display_status.replace("VM ", "")
            try:
                if vm.network_profile and vm.network_profile.network_interfaces:
                    nic_id = vm.network_profile.network_interfaces[0].id; nic_name = nic_id.split('/')[-1]
                    nic = network_client.network_interfaces.get(resource_group, nic_name)
                    if nic.ip_configurations and nic.ip_configurations[0].public_ip_address:
                        pip_id = nic.ip_configurations[0].public_ip_address.id; pip_name = pip_id.split('/')[-1]
                        pip = network_client.public_ip_addresses.get(resource_group, pip_name); public_ip = pip.ip_address
            except Exception: public_ip = "查询失败"
            vm_list.append({"name": vm.name, "location": vm.location, "vm_size": vm.hardware_profile.vm_size, "status": status, "resource_group": resource_group, "public_ip": public_ip, "time_created": vm.time_created.isoformat() if vm.time_created else None})
        return jsonify(vm_list)
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route('/api/regions')
@login_required
@azure_credentials_required
def get_regions():
    try:
        credential, subscription_client = ClientSecretCredential(**g.azure_creds), SubscriptionClient(ClientSecretCredential(**g.azure_creds))
        locations = subscription_client.subscriptions.list_locations(g.azure_creds['subscription_id'])
        region_list = [{"name": loc.name, "display_name": loc.display_name} for loc in locations]
        return jsonify(region_list)
    except Exception as e: return jsonify({"error": f"获取区域列表失败: {str(e)}"}), 500
def _long_running_task(target_func, **kwargs):
    target_func(**kwargs)
@app.route('/api/vm-action', methods=['POST'])
@login_required
@azure_credentials_required
def vm_action():
    data = request.json; task_kwargs = {'credential_dict': g.azure_creds, 'subscription_id': g.azure_creds['subscription_id'], 'action': data.get('action'), 'resource_group': data.get('resource_group'), 'vm_name': data.get('vm_name')}
    threading.Thread(target=_long_running_task, args=(_vm_action_task,), kwargs=task_kwargs).start()
    return jsonify({"message": f"操作已提交，将在后台执行..."})
def _vm_action_task(credential_dict, subscription_id, action, resource_group, vm_name):
    try:
        credential = ClientSecretCredential(**credential_dict); compute_client, resource_client = ComputeManagementClient(credential, subscription_id), ResourceManagementClient(credential, subscription_id)
        if action == 'start': poller = compute_client.virtual_machines.begin_start(resource_group, vm_name)
        elif action == 'stop': poller = compute_client.virtual_machines.begin_deallocate(resource_group, vm_name)
        elif action == 'restart': poller = compute_client.virtual_machines.begin_restart(resource_group, vm_name)
        elif action == 'delete': poller = resource_client.resource_groups.begin_delete(resource_group)
        else: return
        poller.result()
    except Exception as e: app.logger.error(f"后台任务 '{action}' 失败: {e}")
@app.route('/api/vm-change-ip', methods=['POST'])
@login_required
@azure_credentials_required
def change_vm_ip():
    data = request.json; task_kwargs = {'credential_dict': g.azure_creds, 'subscription_id': g.azure_creds['subscription_id'], 'rg_name': data.get('resource_group'), 'vm_name': data.get('vm_name')}
    threading.Thread(target=_long_running_task, args=(_change_ip_task,), kwargs=task_kwargs).start()
    return jsonify({"message": f"正在为虚拟机 {data.get('vm_name')} 申请新的IP地址，请稍后刷新列表。"})
def _change_ip_task(credential_dict, subscription_id, rg_name, vm_name):
    try:
        credential = ClientSecretCredential(**credential_dict); compute_client, network_client = ComputeManagementClient(credential, subscription_id), NetworkManagementClient(credential, subscription_id)
        vm = compute_client.virtual_machines.get(rg_name, vm_name); nic_id = vm.network_profile.network_interfaces[0].id
        nic_name, nic = nic_id.split('/')[-1], network_client.network_interfaces.get(rg_name, nic_id.split('/')[-1])
        ip_config = nic.ip_configurations[0]; old_pip_id = ip_config.public_ip_address.id if ip_config.public_ip_address else None
        if old_pip_id:
            old_pip_name = old_pip_id.split('/')[-1]; ip_config.public_ip_address = None
            network_client.network_interfaces.begin_create_or_update(rg_name, nic_name, nic).result()
            network_client.public_ip_addresses.begin_delete(rg_name, old_pip_name).result()
        new_pip_name = f"pip-{vm_name}-{int(time.time())}"; pip_params = {"location": vm.location, "sku": {"name": "Standard"}, "public_ip_allocation_method": "Static"}
        new_pip = network_client.public_ip_addresses.begin_create_or_update(rg_name, new_pip_name, pip_params).result()
        ip_config.public_ip_address = new_pip; network_client.network_interfaces.begin_create_or_update(rg_name, nic_name, nic).result()
    except Exception as e: app.logger.error(f"更换IP失败 for {vm_name}: {e}")

def _create_vm_task(task_id, credential_dict, subscription_id, vm_name, rg_name, admin_password, data):
    with app.app_context():
        db = get_db()
        db.execute('UPDATE tasks SET status = ? WHERE id = ?', ('running', task_id))
        db.commit()
        try:
            app.logger.info(f"后台任务({task_id})开始：为 {rg_name} 创建VM...")
            credential = ClientSecretCredential(**credential_dict)
            compute_client, network_client, resource_client = ComputeManagementClient(credential, subscription_id), NetworkManagementClient(credential, subscription_id), ResourceManagementClient(credential, subscription_id)
            location, ip_type = data.get('region'), data.get('ip_type')
            os_images = {"debian12": {"publisher": "Debian", "offer": "debian-12", "sku": "12-gen2", "version": "latest"}, "debian11": {"publisher": "Debian", "offer": "debian-11", "sku": "11-gen2", "version": "latest"}, "ubuntu22": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts-gen2", "version": "latest"}, "ubuntu20": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-focal", "sku": "20_04-lts-gen2", "version": "latest"}}
            image_reference, admin_username = os_images.get(data.get('os_image')), "azureuser"
            resource_client.resource_groups.create_or_update(rg_name, {"location": location})
            vnet_poller = network_client.virtual_networks.begin_create_or_update(rg_name, f"vnet-{vm_name}", {"location": location, "address_space": {"address_prefixes": ["10.0.0.0/16"]}, "subnets": [{"name": "default", "address_prefix": "10.0.0.0/24"}]})
            subnet_id = vnet_poller.result().subnets[0].id
            ip_sku = {"name": "Basic"} if ip_type == "Dynamic" else {"name": "Standard"}
            pip_poller = network_client.public_ip_addresses.begin_create_or_update(rg_name, f"pip-{vm_name}", { "location": location, "sku": ip_sku, "public_ip_allocation_method": ip_type })
            public_ip_id = pip_poller.result().id
            nic_poller = network_client.network_interfaces.begin_create_or_update(rg_name, f"nic-{vm_name}", {"location": location, "ip_configurations": [{"name": "ipconfig1", "subnet": {"id": subnet_id}, "public_ip_address": {"id": public_ip_id}}]})
            nic_id = nic_poller.result().id
            azure_params = {"location": location, "storage_profile": {"image_reference": image_reference, "os_disk": {"create_option": "FromImage", "disk_size_gb": data.get('disk_size')}}, "hardware_profile": {"vm_size": data.get('vm_size')}, "os_profile": {"computer_name": vm_name, "admin_username": admin_username, "admin_password": admin_password}, "network_profile": {"network_interfaces": [{"id": nic_id}]}}
            user_data_b64 = data.get('user_data')
            if user_data_b64:
                user_data = base64.b64decode(user_data_b64).decode('utf-8')
                azure_params["os_profile"]["custom_data"] = base64.b64encode(user_data.encode('utf-8')).decode('utf-8')
            vm_poller = compute_client.virtual_machines.begin_create_or_update(rg_name, vm_name, azure_params)
            vm_poller.result()
            final_pip = network_client.public_ip_addresses.get(rg_name, f"pip-{vm_name}")
            success_message = f"🎉 虚拟机 {vm_name} 创建成功! \n    - 公网 IP: {final_pip.ip_address}\n    - 用户名: {admin_username}\n    - 密  码: {admin_password}"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('success', success_message, task_id)); db.commit()
            app.logger.info(f"后台任务({task_id})成功")
        except Exception as e:
            user_friendly_reason = str(e)
            # 【重要】修正了错误码的拼写
            if isinstance(e, HttpResponseError) and e.error and e.error.code == "RequestDisallowedByAzure":
                user_friendly_reason = "账号不支持在该区域创建实例"

            error_message = f"❌ 虚拟机 {rg_name} 创建失败! \n    - 原因: {user_friendly_reason}"
            db.execute('UPDATE tasks SET status = ?, result = ? WHERE id = ?', ('failure', error_message, task_id)); db.commit()
            app.logger.error(f"后台任务({task_id})失败: {str(e)}") # 记录原始错误以供调试
            try:
                resource_client = ResourceManagementClient(ClientSecretCredential(**credential_dict), subscription_id); resource_client.resource_groups.begin_delete(rg_name).wait()
            except: pass
@app.route('/api/create-vm', methods=['POST'])
@login_required
@azure_credentials_required
def create_vm():
    task_id = str(uuid.uuid4()); db = get_db(); db.execute('INSERT INTO tasks (id, status) VALUES (?, ?)', (task_id, 'pending')); db.commit()
    data = request.json
    task_kwargs = {
        'task_id': task_id, 'credential_dict': g.azure_creds, 'subscription_id': g.azure_creds['subscription_id'],
        'vm_name': f"vm-{data.get('region').replace(' ','').lower()}-{int(time.time())}", 'rg_name': f"vm-{data.get('region').replace(' ','').lower()}-{int(time.time())}", 
        'admin_password': generate_password(), 'data': data
    }
    threading.Thread(target=_long_running_task, args=(_create_vm_task,), kwargs=task_kwargs).start()
    return jsonify({ "message": f"创建请求已提交...", "task_id": task_id })
@app.route('/api/task_status/<task_id>')
@login_required
def task_status(task_id):
    task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
    if task is None: return jsonify({'status': 'not_found'}), 404
    return jsonify({'status': task['status'], 'result': task['result']})

init_db()

if __name__ == '__main__':
    # 监听所有网络接口，从环境变量获取端口号
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
