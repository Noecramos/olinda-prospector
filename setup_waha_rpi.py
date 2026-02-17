#!/usr/bin/env python3
"""
Script para configurar WAHA no Raspberry Pi 3B+ via SSH.
Usa a tag correta: devlikeapro/waha:noweb-arm (ARM64, sem browser, ideal para 1GB RAM)
"""

import paramiko
import time
import sys

# Configurações de conexão
HOST = "192.168.1.11"
PORT = 22
USERNAME = "noviapp"
PASSWORD = "Zimplats@2706#2025"

def create_ssh_client():
    """Cria e retorna um cliente SSH conectado."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[INFO] Conectando ao Raspberry Pi em {HOST}...")
    client.connect(HOST, port=PORT, username=USERNAME, password=PASSWORD, timeout=30)
    print("[OK] Conexão SSH estabelecida com sucesso!")
    return client

def run_cmd(client, command, sudo=False, timeout=300):
    """Executa um comando via SSH e retorna stdout/stderr."""
    if sudo:
        # Use bash -c to keep the entire pipeline under sudo
        command = f"echo '{PASSWORD}' | sudo -S bash -c '{command}'"
    
    print(f"\n[CMD] {command[:120]}{'...' if len(command) > 120 else ''}")
    
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    exit_code = stdout.channel.recv_exit_status()
    
    if out:
        print(f"[STDOUT] {out}")
    if err:
        # Filter out sudo password prompt noise
        err_lines = [l for l in err.split('\n') if not l.startswith('[sudo]')]
        err_clean = '\n'.join(err_lines).strip()
        if err_clean:
            print(f"[STDERR] {err_clean}")
    
    print(f"[EXIT] {exit_code}")
    return out, err, exit_code

def main():
    client = None
    try:
        # === ETAPA 0: Conexão ===
        client = create_ssh_client()
        
        print("\n" + "="*60)
        print("ETAPA 0: Diagnóstico do sistema")
        print("="*60)
        
        run_cmd(client, "uname -a")
        run_cmd(client, "free -m")
        run_cmd(client, "docker --version")
        
        # === ETAPA 1: Remover container antigo se existir ===
        print("\n" + "="*60)
        print("ETAPA 1: Limpando containers anteriores")
        print("="*60)
        
        run_cmd(client, "docker stop waha 2>/dev/null; docker rm waha 2>/dev/null; echo 'Limpeza concluída'", sudo=True)
        
        # Limpar imagens antigas para liberar espaço
        run_cmd(client, "docker image prune -f 2>/dev/null", sudo=True)
        
        # === ETAPA 2: Baixar imagem WAHA com tag ARM correta ===
        print("\n" + "="*60)
        print("ETAPA 2: Baixando imagem WAHA (tag noweb-arm para ARM64)")
        print("  Nota: 'noweb' usa engine NOWEB sem Chromium - ideal para 1GB RAM")
        print("  Isso pode demorar vários minutos no Raspberry Pi...")
        print("="*60)
        
        # A tag correta para ARM64 (aarch64) é :noweb-arm ou :arm
        # Usando noweb-arm porque não precisa de Chromium (economiza ~300MB de RAM)
        out, err, exit_code = run_cmd(client, "docker pull devlikeapro/waha:noweb-arm", sudo=True, timeout=600)
        
        if exit_code != 0:
            print("\n[WARN] Falha com noweb-arm, tentando tag :arm (com Chromium)...")
            out, err, exit_code = run_cmd(client, "docker pull devlikeapro/waha:arm", sudo=True, timeout=600)
            waha_image = "devlikeapro/waha:arm"
        else:
            waha_image = "devlikeapro/waha:noweb-arm"
        
        if exit_code != 0:
            print("\n[ERRO FATAL] Não foi possível baixar nenhuma imagem WAHA para ARM.")
            print("[INFO] Verificando imagens disponíveis...")
            run_cmd(client, "docker images", sudo=True)
            sys.exit(1)
        
        # === ETAPA 3: Executar container WAHA ===
        print("\n" + "="*60)
        print(f"ETAPA 3: Iniciando container WAHA ({waha_image})")
        print("="*60)
        
        waha_cmd = (
            f"docker run -d "
            f"--name waha "
            f"--restart always "
            f"-p 3000:3000 "
            f"--memory=512m "
            f"--memory-swap=768m "
            f"-e WHATSAPP_RESTART_ALL_SESSIONS=True "
            f"{waha_image}"
        )
        
        out, err, exit_code = run_cmd(client, waha_cmd, sudo=True, timeout=120)
        
        if exit_code != 0:
            print(f"\n[ERRO] Falha ao iniciar container. Tentando sem limites de memória...")
            run_cmd(client, "docker rm waha 2>/dev/null", sudo=True)
            waha_cmd = (
                f"docker run -d "
                f"--name waha "
                f"--restart always "
                f"-p 3000:3000 "
                f"-e WHATSAPP_RESTART_ALL_SESSIONS=True "
                f"{waha_image}"
            )
            out, err, exit_code = run_cmd(client, waha_cmd, sudo=True, timeout=120)
        
        # Aguardar container inicializar
        print("\n[INFO] Aguardando 20 segundos para o container inicializar...")
        time.sleep(20)
        
        # === ETAPA 4: Verificação ===
        print("\n" + "="*60)
        print("ETAPA 4: Verificação final")
        print("="*60)
        
        run_cmd(client, "docker ps -a --filter name=waha --format 'table {{.ID}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'", sudo=True)
        run_cmd(client, "docker logs waha --tail 30 2>&1", sudo=True)
        run_cmd(client, "free -m")
        
        # Testar se a porta 3000 está respondendo
        out, _, _ = run_cmd(client, "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/ 2>/dev/null || echo 'timeout'")
        
        print("\n" + "="*60)
        print("SETUP COMPLETO!")
        print("="*60)
        print(f"\n🎯 URL do Painel de Controle WAHA:")
        print(f"   http://{HOST}:3000/")
        print(f"\n📋 Imagem utilizada: {waha_image}")
        print(f"\n📋 Para verificar o status:")
        print(f"   ssh {USERNAME}@{HOST} 'docker ps'")
        print(f"\n📋 Para ver logs:")
        print(f"   ssh {USERNAME}@{HOST} 'docker logs waha -f'")
        print(f"\n⚠️  Dica: O Pi tem apenas 1GB de RAM.")
        print(f"   A tag 'noweb' usa o engine NOWEB (sem Chromium), muito mais leve.")
        
    except paramiko.AuthenticationException:
        print(f"[ERRO] Falha na autenticação com {USERNAME}@{HOST}")
        sys.exit(1)
    except paramiko.SSHException as e:
        print(f"[ERRO] Erro SSH: {e}")
        sys.exit(1)
    except TimeoutError:
        print(f"[ERRO] Timeout ao conectar em {HOST}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERRO] {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        if client:
            client.close()
            print("\n[INFO] Conexão SSH encerrada.")

if __name__ == "__main__":
    main()
