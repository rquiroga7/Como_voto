import requests, re
from bs4 import BeautifulSoup

def inspect(year,page):
    url=f'https://www.senado.gob.ar/votaciones/actas?periodo={year}&page={page}'
    r=requests.get(url)
    soup=BeautifulSoup(r.text,'lxml')
    links=soup.find_all('a',href=re.compile(r'/votaciones/detalleActa/'))
    next_link=soup.find('a', string=re.compile('Siguiente', re.I))
    print(year,page,'links',len(links),'next',bool(next_link))
    if next_link:
        print('next href', next_link.get('href'))

for y in [2015,2023]:
    inspect(y,1)
    inspect(y,2)
