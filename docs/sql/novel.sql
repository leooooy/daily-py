CREATE TABLE `novel` (
    `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
    `author` varchar(255) NOT NULL DEFAULT '' COMMENT '作者',
    `introduction` varchar(2000) NOT NULL DEFAULT '' COMMENT '简介',
    `title` varchar(255) NOT NULL DEFAULT '' COMMENT '标签',
    `cover` varchar(255) NOT NULL DEFAULT '' COMMENT '封面',
    `cover_height` int NOT NULL DEFAULT '0' COMMENT '封面图片高度，px',
    `cover_width` int NOT NULL DEFAULT '0' COMMENT '封面图片宽度，px',
    `content` longtext COMMENT '内容',
    `audio_url` varchar(255) NOT NULL DEFAULT '' COMMENT '音频地址',
    `alignment_url` varchar(255) NOT NULL DEFAULT '' COMMENT '音频对齐JSON文件地址',
    `service_level_limits` tinyint NOT NULL DEFAULT '0' COMMENT '服务等级，数字越大限制级越高',
    `click_count` int NOT NULL DEFAULT '0' COMMENT '点击次数',
    `deleted_flag` tinyint NOT NULL DEFAULT '1' COMMENT '删除标记(1:正常 -1:已删除)',
    `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=73 DEFAULT CHARSET=utf8mb3 COMMENT='小说表';