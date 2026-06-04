This is a CloudFlare Asyncron Clean IP scanner.
Cloudflare uses AnyCast to reduce Ping and Increase speed.
But non of all CF Range-IPs are suitable for you.
By this Tool you can scan for Clean IPs in two stage.

Stage 1 :
    - tool ask you for desiered Configuaration you need. also you  need to choose want to search only in IPV4, IPV6 or BOTH.
    - if you have a Domain you can give your Cloudflare API to upload it to your CF automaticly
Stage 2:
    - when tool finde enogh IPs It ask you for Extended Search.
    - in this stage toll search for IPs with higher configuration than average of first stage.
    - first it ask for needed nunber you want.
    - then fill the output table with those IPs from initial search that can pass average of Table in initial search.
    - after that it search untile finde enough IPs as you want to can fill the table by your request or finish all IPs you choose in first stage.

Robot:
This code also can connect to a telegram bot.
this bot writen in Cloudflare worker you can use "worker.js" for this purpose.
the bot work as this :
it make a free Database on cloud flare.
every user can register in bot and get clean CF IPs those are categorized by features like:
    - organization
    - country
    - isp
    - region
    - city
    - longitude
    - latitude
    - ip
    - time & Date of scan
and User can ask for Top 20 results by desired setting.
The only limitation is everyone can only get 4 times more than number of Clean IP it added to data base every mounth.

After user approve to help the others the code asks for user Secret code.
user can get the secret code from the bot at the first time of running of it. also can recover it from the telegram bot menu.
the bot save and update each user {User ID, Username, First name, Last name, Language code, Is bot? (false), Telegram Premium status, Number of Ips added to database, number of used IPs} to prevent any violation of term of use and prevent any false data injection.
each user has a reputation of 100% it calculate by other users results if an IP flag as Flase by other users or numbers of low quality IPs base on search are more than hogh quality in comprition to other users results. thr reputation falls and if the reputation decrease under 50 user ban for atleast 1 mounth and its secret key disabled.
if a user baned three times only admin can revoke the ban.

after the colection of IPs by users.
an other Robot analyze the results and and push the best results to Best Reults Table based on Time: {last 4 hour, last day, last week,} + IPS + City + parameter all together.
Parameters are : ping, jitter, latency, loss, dl, ul.
for example: user can ask for best IPs at: [day, all, Kuthehabdullah, dl]
the bot filter results by [day, isp, city] then for each IP that user push to database calculate the avrage of parameter and sort then by parameter and send top 10.

the analyzer bot is on the other VPS on Huggingface space and update the database every 15 minutes.
also Analyzer bot can make cache of data to reduce calculation if requested data are same just push saved data.

Note: Scanner bot on worker only manage the users and thier keys and get their data and save them in data base and push data base every 15 minutes to analyzer bot.
Note 2 : If analyzer is dead it keep reutls untile the database is filled every time it pushes datas to analyzer bot it flash the data base.
Note 3 : if database filled 5GB Limit it replace previous old datas from the oldest to news with newer data.

You can finde analyzer bot code as in HF_BOT directory. it is a docker base HF spaces bot that handle all things with Huggingface powerfull AI servers free cpu.

TODO: the Rust code will be added in Rust-code directory soon. with a work flow that make a UI for this app to use easily in windows, Linux. Mac. android and other platforms.

Terminal Output:
the output of therminal is like this :
-------------------------------------------------------------------------------------------------------
Parameters :          Ping      Loss    Jitter      latency     Upload Speed        Download Speed
Desired Values :      500 ms    50%     100 ms      1000 ms         0.2 Mbps            3 Mbps
--------------------------------------------------------------------------------------------------------
|---|---------------|--------|-------|-------|--------|----------|----------|
| # |       IP      |Ping(ms)|Loss(%)|Jit(ms)|Lat(ms) | Up(Mbps) |Down(Mbps)|
|---|---------------|--------|-------|-------|--------|----------|----------|
|  1|172.67.219.212 |    133 |0.0    |   100 |   265  |   1.69   |   7.14   |
|  2|104.24.48.107  |    154 |0.0    |    93 |   253  |   1.38   |   7.13   |
|  3|172.66.44.167  |    156 |40.0   |    98 |   239  |   1.06   |   6.13   |
|  4|164.38.155.49  |     68 |0.0    |    56 |   165  |   1.09   |   5.98   |
|  5|104.25.0.244   |    137 |0.0    |    90 |   260  |   1.57   |   5.57   |
|  6|198.41.199.149 |    166 |20.0   |    95 |   275  |   1.38   |   5.43   |
|  7|45.131.7.249   |     60 |0.0    |    62 |   134  |   1.19   |   5.41   |
|  8|104.19.96.193  |    145 |0.0    |   100 |   265  |   1.52   |   5.08   |
|  9|104.25.232.111 |    122 |20.0   |    95 |   230  |   1.32   |   5.00   |
| 10|104.25.24.119  |    136 |0.0    |    77 |   235  |   1.32   |   3.37   |
|---|---------------|--------|-------|-------|--------|----------|----------|
|   |    Average    |    127 |  8.0  |    86 |   232  |   1.35   |    5.62  |
|---|---------------|--------|-------|-------|--------|----------|----------|

IPs for useage save in Selected-IPs.txt for more detail see Selected-IPs.csv

IPs:
-------------------------------------------------------------------------------
172.67.219.212
104.24.48.107
172.66.44.167
164.38.155.49
104.25.0.244
198.41.199.149
45.131.7.249
104.19.96.193
104.25.232.111
104.25.24.119
--------------------------------------------------------------------------------

You Choose to be a Selfish creature that dont Help Others. to be a human kind next time choose Yes i want to participate in Clean IP collection. :(

    I hope you get hit by a truck!