# Same Node.js major as the server Pi
FROM node:20-bullseye-slim

ENV TZ=Europe/Paris NODE_ENV=production
WORKDIR /app

# Only the dependencies live in the image, installed exactly from the lock file.
COPY server/web/package.json server/web/package-lock.json ./
RUN npm ci --omit=dev

USER node
CMD ["node", "server.js"]
