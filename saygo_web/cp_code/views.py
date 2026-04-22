import os
import paramiko
from django.http import HttpResponse, HttpResponseServerError


# Create your views here.
def code(request):
    ssh_host = os.getenv('CP_SSH_HOST')
    ssh_port = int(os.getenv('CP_SSH_PORT', 22))
    ssh_user = os.getenv('CP_SSH_USER', 'root')
    ssh_password = os.getenv('CP_SSH_PASSWORD')

    if not ssh_host:
        return HttpResponseServerError('SSH host is not configured.')

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(hostname=ssh_host, port=ssh_port, username=ssh_user, password=ssh_password)
        _, stdout, _ = client.exec_command("cat /opt/corekeeper/GameID.txt")
        result = stdout.read().decode().strip()
    except (paramiko.AuthenticationException,
            paramiko.SSHException,
            OSError) as e:
        return HttpResponseServerError(f'SSH connection failed: {e}')
    finally:
        client.close()

    return HttpResponse(result)