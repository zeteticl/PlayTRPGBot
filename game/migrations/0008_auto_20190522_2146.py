# Generated by Django 2.2.1 on 2019-05-22 21:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0007_auto_20190522_1917'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='description',
            field=models.CharField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='variable',
            name='group',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
