-- Days 101-104: Medallion Architecture.
--
-- Po umolchaniyu dbt skleivaet skhemu kak <target.schema>_<custom>:
-- +schema: gold v dev daet main_gold. Eto khorosho dlya dev i CI -
-- u kazhdogo razrabotchika svoy prefiks, nikto ne pishet v chuzhoy gold.
--
-- V prod nuzhny rovno BRONZE / SILVER / GOLD - na nikh vydany granty
-- (sm. snowflake_setup/22_medallion_layers.sql), i BI chitaet GOLD
-- bez prefiksov. Poetomu na target prod custom-skhema beretsya kak est.

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name == 'prod' -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
