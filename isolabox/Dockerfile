FROM php:8.3-apache

# Enable Apache modules
RUN a2enmod rewrite headers expires deflate

# Set document root
ENV APACHE_DOCUMENT_ROOT=/var/www/html/public
RUN sed -ri -e 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/sites-available/*.conf
RUN sed -ri -e 's!/var/www/!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/apache2.conf /etc/apache2/conf-available/*.conf

# Allow .htaccess overrides
RUN sed -i '/<Directory \/var\/www\/>/,/<\/Directory>/ s/AllowOverride None/AllowOverride All/' /etc/apache2/apache2.conf

# Copy application
COPY .env /var/www/html/.env
COPY config/ /var/www/html/config/
COPY includes/ /var/www/html/includes/
COPY pages/ /var/www/html/pages/
COPY public/ /var/www/html/public/
COPY router.php /var/www/html/router.php

# Set permissions
RUN chown -R www-data:www-data /var/www/html

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

EXPOSE 80
