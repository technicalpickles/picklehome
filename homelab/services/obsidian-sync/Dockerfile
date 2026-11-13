FROM node:26-alpine

RUN npm install -g obsidian-headless

WORKDIR /vault

CMD ["ob", "sync", "--continuous"]
