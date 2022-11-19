# Мониторинг объявлений на goszakup.kz

### Installation
`pip install scrapy`  
`pip install requests-toolbelt`  
`pip install backoff`
[Установить NCANode](https://ncanode.kz/)

### Usage
Запустить NCANode с настройками по умолчанию  
```
cd requests  
python3 multiprocessor.py --config="FULL/PATH/TO/CONFIG.json"
```

| parameter     | comment                                                                                                                                                                               |   |
|---------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| config        | путь к файлу с конфигом                                                                                                                                                               |   |
| proxy_monitor | [OPTIONAL] прокси для мониторинга статуса заявки                                                                                                                                      |   |
| proxy_apply   | [OPTIONAL] прокси для подачи заявки                                                                                                                                                   |   |
| fake_monitor  | [OPTIONAL] [DEBUG]используется для отладки скрипта   означает количество проверок статуса объявления перед тем как начать подаваться на нее независимо от статуса заявки.  Default: 0 |   |
| publish       | [OPTIONAL] [DEBUG] хотим ли мы публиковать сформированную заявку или останавливаемся на последнем шаге перед подачей                                                                  |   |
| infinite      | [OPTIONAL] [DEBUG] бесконечная подача в цикле                                                                                   

### CONFIG
Для запуска приложения необходимо создать конфиг в виде json файла  
Структура конфига становится ясна из файла для его генерации  
https://gist.github.com/necuk/5e1e01ba1cfba4b96fe0b785ade9c667   
