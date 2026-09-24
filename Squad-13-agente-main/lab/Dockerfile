# Imagem base fixada por digest, não só por tag: uma tag como "8.3-apache" é
# móvel e pode receber um bump de minor a qualquer momento, produzindo
# ambientes divergentes entre turmas que clonam o repositório em datas
# diferentes ao longo do semestre.
FROM php@sha256:060ed9c0f6e4bbe4f8b25a34ca1ec596b96d8f4011cf7ee7eb6b7eecf01cb74f

# Versão do GLPI fixada deliberadamente, pela mesma razão da imagem base
# acima: evitar que turmas diferentes acabem com ambientes divergentes.
ARG GLPI_VERSION=11.0.8

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpng-dev libjpeg-dev libfreetype6-dev libzip-dev libicu-dev \
      libxml2-dev libbz2-dev libldap2-dev libsodium-dev \
      default-mysql-client curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-configure ldap --with-libdir="lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)" \
    && docker-php-ext-install -j"$(nproc)" \
       mysqli gd intl zip bz2 ldap exif opcache sodium bcmath

RUN a2enmod rewrite

RUN curl -fsSL \
      "https://github.com/glpi-project/glpi/releases/download/${GLPI_VERSION}/glpi-${GLPI_VERSION}.tgz" \
      -o /tmp/glpi.tgz \
    && tar -xzf /tmp/glpi.tgz -C /var/www \
    && rm /tmp/glpi.tgz \
    && chown -R www-data:www-data /var/www/glpi

# GLPI 11 serve a partir de public/
ENV APACHE_DOCUMENT_ROOT=/var/www/glpi/public
RUN sed -ri 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' \
      /etc/apache2/sites-available/*.conf /etc/apache2/apache2.conf \
    && printf '<Directory /var/www/glpi/public>\n  AllowOverride All\n  Require all granted\n  RewriteEngine On\n  RewriteCond %%{REQUEST_FILENAME} !-f\n  RewriteRule ^(.*)$ index.php [QSA,L]\n</Directory>\n' \
       > /etc/apache2/conf-available/glpi.conf \
    && a2enconf glpi

WORKDIR /var/www/glpi
