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
    def __init__(self, websocket: WebSocket, device_id: str, role: str = 'admin', identity: str = 'normal'):
        self.ws = websocket
        self.device_id = device_id
        self.role = role        # Display username (e.g. 'user', 'root', 'admin')
        self.identity = identity  # Access level: 'normal' or 'privileged'
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
        
        # 2. Determine login credentials based on identity (not role string)
        is_normal = self.identity == 'normal'
        if is_normal:
            if not creds.get('normal_username'):
                await self.ws.send_text(json.dumps({"type": "error", "message": "Normal account not configured. Please set it in Asset Management."}))
                await self.ws.close(code=4001)
                return
            login_user = creds.get('normal_username')
            login_pwd = creds.get('normal_password')
        else:
            # Privileged access: use admin credentials
            login_user = creds.get('admin_username') or creds.get('username')
            login_pwd = creds.get('admin_password') or creds.get('password')

        try:
            # 3. Establish SSH Connection
            logger.info(f"[Terminal] Connecting to {device['ip_address']} as {login_user} (identity={self.identity})...")
            self.ssh_conn = await asyncssh.connect(
                device['ip_address'],
                username=login_user,
                password=login_pwd,
                known_hosts=None, # Safety: ignore host key for now
                client_factory=None
            )
            # create_process() without command starts a shell
            self.ssh_chan = await self.ssh_conn.create_process(
                term_type='xterm-256color',
                term_size=(80, 24)
            )
            
            logger.info(f"[Terminal] xterm-256color Session established for {device['hostname']} as {login_user}")
            
            # Start IO tasks
            await asyncio.gather(
                self._upstream(),
                self._downstream()
            )
        except Exception as e:
            logger.error(f"[Terminal] Connection failed or terminated: {e}", exc_info=True)
            try:
                await self.ws.send_text(json.dumps({"type": "error", "message": str(e)}))
                await self.ws.close(code=1011)
            except:
                pass

    async def _upstream(self):
        """Websocket -> SSH Stdin"""
        try:
            async for message in self.ws.iter_text():
                data = json.loads(message)
                if data['type'] == 'input':
                    # DEBUG: Log input characters
                    logger.debug(f"[Terminal] Stdin write: {repr(data['data'])}")
                    self.ssh_chan.stdin.write(data['data'])
                    await self.ssh_chan.stdin.drain()
                elif data['type'] == 'resize':
                    try:
                        self.ssh_chan.change_terminal_size(data['cols'], data['rows'])
                    except Exception as e:
                        logger.warning(f"[Terminal] Resize failed: {e}")
        except Exception as e:
            logger.error(f"[Terminal] Upstream error: {e}")

    async def _downstream(self):
        """SSH Stdout -> Websocket"""
        try:
            while not self.ssh_chan.stdout.at_eof():
                output = await self.ssh_chan.stdout.read(4096)
                if output:
                    await self.ws.send_text(json.dumps({"type": "output", "data": output}))
                await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"[Terminal] Downstream error: {e}")
        finally:
            logger.info(f"[Terminal] Session closed for {self.device_id}")
            try:
                await self.ws.close()
            except:
                pass

@router.websocket("/access/terminal/{device_id}")
async def terminal_websocket(
    websocket: WebSocket, 
    device_id: str, 
    role: str = Query('admin'),
    identity: str = Query('normal')
):
    await websocket.accept()
    session = TerminalSession(websocket, device_id, role, identity)
    await session.connect()
