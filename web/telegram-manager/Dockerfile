FROM node:24-alpine
WORKDIR /service
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY service.ts server.ts ./
USER node
EXPOSE 8080
CMD ["npm", "start"]
