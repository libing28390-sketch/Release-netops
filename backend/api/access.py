import asyncio
import json
import logging
import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
from database import get_db_connection
from services.vault_service import resolve_device_credentials
from core.crypto import decrypt_credential

router = APIRouter(tags=["access"])
logger = logging.getLogger(__name__)

class TerminalSession:
    def __init__(self, websocket: WebSocket, device_id: str, role: str = 'admin'):
        self.ws = websocket
        self.device_id = device_id
        self.role = role
        self.ssh_conn = None
        self.ssh_chan = None

    async def connect(self):
        # 1. Fetch device & credentials
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (self.device_id,)).fetchone()
            if not row:
                await self.ws.close(code=4004, reason="Device not found")
                return
            device = dict(row)
        finally:
            conn.close()

        creds = resolve_device_credentials(device)
        
        # 2. Logic to determine login creds (aligned with PAM rotation logic)
        platform = (device.get('platform') or '').lower()
        is_server = any(x in platform for x in ['linux', 'ubuntu', 'centos', 'debian'])
        
        # If server, we always use admin to log in (more reliable for subsequent su/sudo)
        login_user = creds.get('admin_username') or creds.get('username')
        login_pwd = creds.get('admin_password') or creds.get('password')
        
        # Override if specific role requested and it's not a server
        if not is_server and self.role == 'normal':
            login_user = creds.get('normal_username') or login_user
            login_pwd = creds.get('normal_password') or login_pwd

        try:
            # 3. Establish SSH Connection
            logger.info(f"[Terminal] Connecting to {device['ip_address']} as {login_user}...")
            self.ssh_conn = await asyncssh.connect(
                device['ip_address'],
                username=login_user,
                password=login_pwd,
                known_hosts=None, # Safety: ignore host key for now
                client_factory=None
            )
            self.ssh_chan, _ = await self.ssh_conn.create_session(
                asyncssh.SSHClientProcess,
                term_type='xterm-256color',
                term_size=(80, 24)
            )
            logger.info(f"[Terminal] Connected successfully to {device['hostname']}")
            
            # Start IO tasks
            await asyncio.gather(
                self._upstream(),
                self._downstream()
            )
        except Exception as e:
            logger.error(f"[Terminal] Connection failed: {e}")
            await self.ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            await self.ws.close(code=1011)

    async def _upstream(self):
        """Websocket -> SSH Stdin"""
        try:
            async for message in self.ws.iter_text():
                data = json.loads(message)
                if data['type'] == 'input':
                    self.ssh_chan.write(data['data'])
                elif data['type'] == 'resize':
                    self.ssh_chan.set_terminal_size(data['cols'], data['rows'])
        except Exception:
            pass

    async def _downstream(self):
        """SSH Stdout -> Websocket"""
        try:
            while not self.ssh_chan.at_eof():
                output = await self.ssh_chan.read(4096)
                if output:
                    await self.ws.send_text(json.dumps({"type": "output", "data": output}))
                await asyncio.sleep(0.01)
        except Exception:
            pass
        finally:
            await self.ws.close()

@router.websocket("/access/terminal/{device_id}")
async def terminal_websocket(
    websocket: WebSocket, 
    device_id: str, 
    role: str = Query('admin')
):
    await websocket.accept()
    session = TerminalSession(websocket, device_id, role)
    await session.connect()
