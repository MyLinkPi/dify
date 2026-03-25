docker images|grep -v REPOSITORY|awk '{print $3}'|xargs -n 1 docker rmi
