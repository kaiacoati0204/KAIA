# -*- coding: utf-8 -*-
"""Extrai só o ITENS_PROVA_<ano>.csv de dentro do zip de microdados do INEP.

O zip tem ~550 MB e o arquivo que interessa tem poucos KB. ZIP guarda o índice no
FIM do arquivo, então dá para ler o índice por HTTP Range e baixar só o trecho do
membro escolhido — sem puxar o pacote inteiro.
"""
import io
import sys
import zipfile
import subprocess


class ArquivoRemoto(io.RawIOBase):
    """File-like sobre HTTP Range, para o zipfile fazer seek sem baixar tudo."""

    # curl em vez de requests: o certificado do download.inep.gov.br vem com cadeia
    # incompleta e o certifi do Python recusa. O curl usa o store do sistema e valida
    # — melhor trocar de transporte do que desligar a verificação.
    def __init__(self, url):
        self.url = url
        self.pos = 0
        cab = subprocess.run(["curl", "-sIL", "--max-time", "60", url],
                             capture_output=True, text=True).stdout
        tam = [l.split(":")[1].strip() for l in cab.splitlines()
               if l.lower().startswith("content-length:")]
        self.tamanho = int(tam[-1])
        self.baixado = 0

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = (offset if whence == io.SEEK_SET else
                    self.pos + offset if whence == io.SEEK_CUR else
                    self.tamanho + offset)
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def read(self, n=-1):
        if n < 0:
            n = self.tamanho - self.pos
        if n == 0 or self.pos >= self.tamanho:
            return b""
        fim = min(self.pos + n, self.tamanho) - 1
        dados = subprocess.run(
            ["curl", "-sL", "--max-time", "300", "-r", f"{self.pos}-{fim}", self.url],
            capture_output=True).stdout
        self.pos += len(dados)
        self.baixado += len(dados)
        return dados


def extrair(ano, destino):
    url = f"https://download.inep.gov.br/microdados/microdados_enem_{ano}.zip"
    remoto = ArquivoRemoto(url)
    print(f"{ano}: zip com {remoto.tamanho/1048576:.0f} MB — lendo só o índice")
    with zipfile.ZipFile(remoto) as z:
        alvos = [n for n in z.namelist() if "ITENS_PROVA" in n.upper()]
        if not alvos:
            print(f"  nenhum ITENS_PROVA. Membros: {z.namelist()[:12]}")
            return None
        nome = alvos[0]
        info = z.getinfo(nome)
        print(f"  achado: {nome}  ({info.file_size/1024:.0f} KB descompactado)")
        dados = z.read(nome)
    with open(destino, "wb") as f:
        f.write(dados)
    print(f"  salvo em {destino}  |  baixados {remoto.baixado/1048576:.1f} MB de "
          f"{remoto.tamanho/1048576:.0f} MB")
    return destino


if __name__ == "__main__":
    ano = sys.argv[1] if len(sys.argv) > 1 else "2023"
    extrair(ano, sys.argv[2] if len(sys.argv) > 2 else f"itens_{ano}.csv")
