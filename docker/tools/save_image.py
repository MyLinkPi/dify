import os
l = os.popen('docker ps |awk {\'print $2\'}|grep -v ID').read().strip().split('\n')
for i in l:
    os.system('docker save -o ' + i.replace('/','_') + '.tar ' + i)
