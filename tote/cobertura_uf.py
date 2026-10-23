"""
Reproduz o mapa de cobertura da APS por macrorregião para uma UF (M22, waset).

Porta fiel das células 16, 17 e 19 de scripts/cobertura.ipynb, com duas diferenças:
o repositório é lido sem escrita (as entradas fatiadas são remontadas numa pasta de
trabalho dentro da saída) e, além dos mapas HTML, grava a tabela por setor em CSV
ordenado, que é o que se compara entre rodadas (o HTML do folium tem ids aleatórios).

Uso: python cobertura_uf.py --repo /projeto --uf AL --saida /saida/mapas/<rodada>
Saída: <saida>/tabela/<UF>.csv, <saida>/html/<UF>_<MACRO>.html, <saida>/erros.txt,
       <saida>/resumo.txt. Código 0 = nenhuma macro com erro; 2 = alguma macro com erro.
"""
import argparse
import glob
import hashlib
import os
import shutil
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--repo', required=True)
ap.add_argument('--uf', required=True)
ap.add_argument('--saida', required=True)
args = ap.parse_args()

REPO = os.path.abspath(args.repo)
UF = args.uf.upper()
SAIDA = os.path.abspath(args.saida)
if os.path.exists(SAIDA):
    sys.exit(f'[ERRO] saída já existe (re-execução não sobrescreve): {SAIDA}')
TRABALHO = os.path.join(SAIDA, 'trabalho')


def remonta(padrao, destino):
    partes = sorted(glob.glob(padrao))
    if not partes:
        sys.exit(f'[ERRO] nenhuma parte para {destino}')
    with open(destino, 'wb') as out:
        for p in partes:
            with open(p, 'rb') as f:
                shutil.copyfileobj(f, out)


# pasta de trabalho: links para o repo + entradas fatiadas remontadas (o repo fica intocado)
for sub in ['shapes', 'dados/distancias', 'scripts']:
    os.makedirs(os.path.join(TRABALHO, sub))
for f in glob.glob(f'{REPO}/shapes/*'):
    if '_part_' not in f:
        os.symlink(f, os.path.join(TRABALHO, 'shapes', os.path.basename(f)))
for f in glob.glob(f'{REPO}/dados/distancias/*.parquet'):
    os.symlink(f, os.path.join(TRABALHO, 'dados/distancias', os.path.basename(f)))
remonta(f'{REPO}/shapes/setores_ligth_processado_part_*',
        os.path.join(TRABALHO, 'shapes/setores_ligth_processado.gpkg'))
if not os.path.exists(os.path.join(TRABALHO, f'dados/distancias/{UF}.parquet')):
    remonta(f'{REPO}/dados/distancias/{UF}_part_*',
            os.path.join(TRABALHO, f'dados/distancias/{UF}.parquet'))
os.chdir(os.path.join(TRABALHO, 'scripts'))  # utils.py procura '../shapes' e '../dados'

sys.path.insert(0, REPO)
import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium.plugins import MarkerCluster
from shapely import Point
from utils import *  # noqa: E402,F403 — como no notebook

path_map = os.path.join(SAIDA, 'html')
os.makedirs(path_map)
os.makedirs(os.path.join(SAIDA, 'tabela'))


# --- célula 16 (sem alteração) ---
def lista_setores(cnes_id, nivel):
    return distancias.loc[(distancias.CO_CNES == cnes_id) & (distancias.nivel == nivel), 'ID_SETOR'].to_list()

def total_setores(cnes_id, nivel):
    return setores_temp.loc[setores_temp.id_setor.isin(lista_setores(cnes_id, nivel)), ['populacao', 'pop_captada', 'populacao_ajustada']].sum()

def aloca_parcial(setores_nivel, cadastro_disponivel):
    temp = setores_temp.loc[setores_temp['id_setor'].isin(setores_nivel)].copy()
    temp["falta"] = temp["populacao"] - temp["pop_captada"]
    temp["percent"] = temp["falta"] / temp["falta"].sum()
    temp["recebe"] = np.floor(temp["percent"] * cadastro_disponivel).astype(int)
    temp["pop_captada"] = temp["recebe"] + temp["pop_captada"]
    if (temp["pop_captada"].sum() > temp["populacao"].sum()):
        print("ERRO")
    setores_temp.loc[setores_temp['id_setor'].isin(setores_nivel), 'pop_captada'] = temp["pop_captada"]

def aloca_todos(setores_nivel):
    setores_temp.loc[setores_temp['id_setor'].isin(setores_nivel), 'pop_captada'] = setores_temp.loc[setores_temp['id_setor'].isin(setores_nivel), 'populacao']

def distribuir_cadastros(cnes_id, cadastros_disponiveis, ajustaCadastros=False):
    niveis_distancia = distancias.loc[distancias.CO_CNES == cnes_id, 'nivel'].unique().tolist()
    if len(niveis_distancia) == 0:
        return
    for nivel in niveis_distancia:
        total_do_nivel = total_setores(cnes_id, nivel)
        setores_nivel = lista_setores(cnes_id, nivel)
        if ajustaCadastros:
            populacao_total = int(total_do_nivel["populacao_ajustada"])
        else:
            populacao_total = int(total_do_nivel["populacao"])
        populacao_captada = int(total_do_nivel['pop_captada'])
        populacao_restante = populacao_total - populacao_captada
        if cadastros_disponiveis >= populacao_restante:
            aloca_todos(setores_nivel)
            cadastros_disponiveis -= populacao_restante
        else:
            aloca_parcial(setores_nivel, cadastros_disponiveis)
            cadastros_disponiveis = 0
            return
        if cadastros_disponiveis <= 0:
            return


# --- célula 17 ---
setores = gpd.read_file('../shapes/setores_ligth_processado.gpkg')
setores.columns = [col.lower() for col in setores.columns]
macro = gpd.read_file('../shapes/macro.gpkg')
macro = macro.astype({'CO_MACRORREGIONAL': 'Int64'})
lista_macro = macro[['CD_MUN', 'CD_UF', 'CO_MACRORREGIONAL', 'NO_MACRORREGIONAL']].rename(columns={'CD_UF': 'SG_UF'})

# --- célula 19, para uma UF ---
coluna_cadastros = 'PARAMETRO_TOTAL'
export = True
ajustaCadastros = False
tabelas, erros = [], []
macros = lista_macro.loc[lista_macro.SG_UF == co_uf_ibge.get(UF), 'CO_MACRORREGIONAL'].unique()
for MACRO in macros:
    try:
        limites = [2**(n-1) for n in range(1, 7)]
        limites.insert(0, 0)
        distancias = get_distancias(UF)
        distancias['nivel'] = pd.cut(distancias['distancia'], bins=limites, labels=[i for i in range(0, 6)])
        unidades = get_unidades(UF, MACRO)
        unidades['ACOMPANHADOS_TOTAIS'] = unidades.groupby('CO_CNES')['CADASTROS_ACOMPANHADOS'].transform('sum')
        unidades['CADASTROS_TOTAIS'] = unidades.groupby('CO_CNES')['CADASTROS_VINCULADOS'].transform('sum')
        unidades['PREVINE_TOTAIS'] = unidades.groupby('CO_CNES')['CADASTROS_PREVINE'].transform('sum')
        unidades['PARAMETRO_TOTAL'] = unidades.groupby('CO_CNES')['PARAMETRO_CADASTRAL'].transform('sum')
        unidades = unidades.groupby(['CO_CNES', 'CO_MUNICIPIO', 'LATITUDE', 'LONGITUDE']).agg({'ACOMPANHADOS_TOTAIS': 'mean', 'CADASTROS_TOTAIS': 'mean', 'PREVINE_TOTAIS': 'mean', 'PARAMETRO_TOTAL': 'mean'}).reset_index()
        unidades['geometry'] = [Point(long, lat) for long, lat in zip(unidades['LONGITUDE'], unidades['LATITUDE'])]
        unidades = unidades[['CO_CNES', 'CO_MUNICIPIO', 'ACOMPANHADOS_TOTAIS', 'CADASTROS_TOTAIS', 'PREVINE_TOTAIS', 'PARAMETRO_TOTAL', 'geometry']]
        unidades = gpd.GeoDataFrame(unidades, geometry='geometry')
        unidades = unidades.set_crs(setores.crs)
        unidades['id_setor'] = gpd.sjoin(unidades, setores, how='left', predicate='within')['id_setor']
        unidades = unidades.astype({'ACOMPANHADOS_TOTAIS': 'Int64', 'CADASTROS_TOTAIS': 'Int64', 'PREVINE_TOTAIS': 'Int64', 'PARAMETRO_TOTAL': 'Int64'})

        municipios = set(unidades.CO_MUNICIPIO)
        processado = []
        for municipio in municipios:
            ubs_temp = unidades.loc[unidades.CO_MUNICIPIO == municipio]
            setores_temp = setores.loc[setores.co_municipio == municipio]
            for _, row in ubs_temp.iterrows():
                distribuir_cadastros(row['CO_CNES'], row[coluna_cadastros], ajustaCadastros)
            processado.append(setores_temp)

        resultado = pd.concat(processado)
        if ajustaCadastros:
            resultado['valor'] = resultado.pop_captada / resultado.populacao_ajustada
        else:
            resultado['valor'] = resultado.pop_captada / resultado.populacao
        resultado['valor_formatado'] = resultado['valor'].apply(lambda x: f"{x:.2%}")
        resultado = gpd.GeoDataFrame(resultado, geometry='geometry')
        resultado = resultado.set_crs(setores.crs)
        resultado['geoid'] = resultado.index.astype(str)

        t = pd.DataFrame(resultado[['id_setor', 'co_municipio', 'populacao', 'pop_captada', 'valor']])
        t.insert(0, 'co_macrorregional', int(MACRO))
        tabelas.append(t)

        unidades_cnes = get_unidades(UF, MACRO)
        unidades_cnes = unidades_cnes.groupby(['CO_CNES', 'NO_FANTASIA', 'NO_MUNICIPIO', 'NO_LOGRADOURO', 'DS_TIPO_UNIDADE']).agg({'CO_EQUIPE': list, 'TP_EQUIPE': list, 'DS_EQUIPE': list, 'SG_EQUIPE': list, 'CO_AREA': list, 'NO_REFERENCIA': list, 'ST_EQUIPE_VALIDA': list, 'CADASTROS_ACOMPANHADOS': list, 'CADASTROS_VINCULADOS': list, 'CADASTROS_PREVINE': list, 'PARAMETRO_CADASTRAL': list, 'LATITUDE': 'mean', 'LONGITUDE': 'mean', 'DENTRO_MUNICIPIO': 'max'}).reset_index()
        unidades_cnes['geometry'] = [Point(point[0], point[1]) for point in zip(unidades_cnes.LONGITUDE, unidades_cnes.LATITUDE)]
        centroMacro = macro.loc[macro.CO_MACRORREGIONAL == int(MACRO)].representative_point()

        map = folium.Map(location=[centroMacro.y, centroMacro.x], tiles='cartodbpositron', control_scale=True, prefer_canvas=True, zoom_start=11)
        marker_cluster = MarkerCluster(name="Unidades básicas de saúde")
        for index, cnes in unidades_cnes.iterrows():
            caixa = create_box(cnes, export)
            folium.Marker([cnes.geometry.y, cnes.geometry.x], icon=folium.Icon(color="orange", icon="house-medical", prefix='fa'), popup=caixa, tooltip=cnes.NO_FANTASIA).add_to(marker_cluster)
        folium.Choropleth(
            geo_data=resultado, name='Cobertura', data=resultado, columns=['geoid', 'valor'],
            key_on='feature.id', fill_color='Blues', fill_opacity=0.8, line_opacity=0.5,
            line_color='black', line_weight=.5, smooth_factor=1.0, nan_fill_color="White",
            legend_name='Percentual de cobertura').add_to(map)
        folium.features.GeoJson(resultado, name='Informações dos setores',
            style_function=lambda x: {'color': 'transparent', 'fillColor': 'transparent', 'weight': 0},
            tooltip=folium.features.GeoJsonTooltip(fields=['populacao', 'pop_captada', 'valor_formatado'],
                                                   aliases=['População residente', 'População coberta', 'Percentual de cobertura'],
                                                   labels=True, sticky=False),
            highlight_function=lambda x: {'fillColor': '#ffffff', 'color': '#ffffff', 'fillOpacity': .5, 'weight': 0.1}).add_to(map)
        marker_cluster.add_to(map)
        folium.LayerControl().add_to(map)
        export_map(map, f"{path_map}/{UF}_{MACRO}.html", export)
    except Exception as e:
        erros.append(f'Problemas em gerar os dados de: {UF} - {MACRO}. {type(e).__name__}: {e}')

# --- tabela comparável, erros e resumo (só contagens) ---
csv = os.path.join(SAIDA, 'tabela', f'{UF}.csv')
if tabelas:
    tab = pd.concat(tabelas).sort_values(['co_macrorregional', 'id_setor']).reset_index(drop=True)
else:
    tab = pd.DataFrame(columns=['co_macrorregional', 'id_setor', 'co_municipio', 'populacao', 'pop_captada', 'valor'])
tab.to_csv(csv, index=False, float_format='%.10f')
with open(os.path.join(SAIDA, 'erros.txt'), 'w') as f:
    f.write(''.join(e + '\n' for e in erros))
sha = hashlib.sha256(open(csv, 'rb').read()).hexdigest()
resumo = [
    f'uf={UF}',
    f'macros={len(macros)}',
    f'macros_erro={len(erros)}',
    f'html={len(glob.glob(path_map + "/*.html"))}',
    f'setores={len(tab)}',
    f'pop_total={int(tab.populacao.sum()) if len(tab) else 0}',
    f'pop_captada={int(tab.pop_captada.sum()) if len(tab) else 0}',
    f'sha256_tabela={sha}',
]
with open(os.path.join(SAIDA, 'resumo.txt'), 'w') as f:
    f.write('\n'.join(resumo) + '\n')
shutil.rmtree(TRABALHO)
print('\n'.join(resumo))
sys.exit(2 if erros else 0)
