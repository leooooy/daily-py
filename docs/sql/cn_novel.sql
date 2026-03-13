CREATE TABLE `media_resource` (
      `id` varchar(255) COLLATE utf8mb4_general_ci NOT NULL,
      `media_name` text COLLATE utf8mb4_general_ci,
      `introduce` text COLLATE utf8mb4_general_ci,
      `media_url` text COLLATE utf8mb4_general_ci,
      `author` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
      `media_cover_url` text COLLATE utf8mb4_general_ci,
      `media_cover_height` int DEFAULT NULL,
      `media_cover_width` int DEFAULT NULL,
      `media_size` bigint DEFAULT NULL,
      `service_level_limits` int DEFAULT NULL,
      `media_category` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
      `visibility` varchar(32) COLLATE utf8mb4_general_ci DEFAULT NULL,
      `user_id` varchar(255) COLLATE utf8mb4_general_ci DEFAULT NULL,
      `media_state` tinyint DEFAULT NULL,
      `reward_token` bigint DEFAULT NULL,
      `likes_count` bigint DEFAULT NULL,
      `collection_count` bigint DEFAULT NULL,
      `provider_module` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
      `deleted_flag` tinyint DEFAULT NULL,
      `created_time` datetime DEFAULT NULL,
      `updated_time` datetime DEFAULT NULL,
      `show_order` int DEFAULT NULL,
      `xgame_support` int DEFAULT NULL,
      `vr_mode` int DEFAULT '0',
      `common` bit(1) DEFAULT b'1',
      PRIMARY KEY (`id`) USING BTREE,
      KEY `idx_media_resource_optimized` (`deleted_flag`,`common`,`visibility`,`media_state`,`service_level_limits` DESC,`show_order` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC;


CREATE TABLE `recommond_table` (
   `id` int NOT NULL AUTO_INCREMENT COMMENT 'ID',
   `name` text CHARACTER SET utf8mb3 COMMENT '名字',
   `tag` varchar(255) CHARACTER SET utf8mb3 DEFAULT NULL COMMENT '标签',
   `introduce` varchar(255) CHARACTER SET utf8mb3 DEFAULT NULL COMMENT '简介',
   `poster` varchar(255) CHARACTER SET utf8mb3 DEFAULT NULL COMMENT '封面',
   `author` varchar(255) CHARACTER SET utf8mb3 DEFAULT NULL COMMENT '作者',
   `instruct_path` text CHARACTER SET utf8mb3 COMMENT '蓝牙指令',
   `status` int DEFAULT '0' COMMENT '状态',
   `file_path` varchar(255) DEFAULT NULL COMMENT '文件地址',
   `vr_video_url` varchar(255) DEFAULT NULL COMMENT 'vr视频地址',
   `type` varchar(255) DEFAULT NULL COMMENT '类型：普通模式  normal\n视频模式  video\n音频模式 audio\n音乐模式 music',
   `duration` bigint DEFAULT NULL COMMENT '时长(毫秒) duration',
   `image_height` int DEFAULT NULL COMMENT '图片宽度，px',
   `image_width` int DEFAULT NULL COMMENT '图片高度，px',
   `service_level_limits` int DEFAULT NULL COMMENT '限制等级（0 大陆用户可用,1国外限制级 ,2 限制级别上升 ',
   `deleted_flag` tinyint DEFAULT NULL COMMENT '1:未删除\r\n-1：删除',
   `create_time` datetime DEFAULT NULL COMMENT '创建时间',
   `update_time` datetime DEFAULT NULL COMMENT '修改时间',
   `likes_count` bigint DEFAULT '0' COMMENT '喜欢数量',
   `collection_count` bigint DEFAULT '0' COMMENT '收藏数量',
   `fake_collection_count` bigint DEFAULT NULL COMMENT '假收藏数',
   `is_old_version` tinyint(1) DEFAULT '0' COMMENT '是否是旧版（0 旧版  1 新版）',
   `novel_text_url` varchar(255) DEFAULT NULL COMMENT '小说url',
   `show_order` int DEFAULT '890' COMMENT '排序',
   `first_frame_url` varchar(255) DEFAULT NULL COMMENT '第一帧url',
   `gender` tinyint DEFAULT NULL COMMENT '性别',
   `selected_level` int DEFAULT '0',
   `xgame_supported` bit(1) DEFAULT b'0' COMMENT 'xgame支持',
   `vr_mode` int DEFAULT '0',
   PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2025043002 DEFAULT CHARSET=latin1 ROW_FORMAT=DYNAMIC;



INSERT INTO `toy`.`media_resource` (`id`, `media_name`, `introduce`, `media_url`, `author`, `media_cover_url`, `media_cover_height`, `media_cover_width`, `media_size`, `service_level_limits`, `media_category`, `visibility`, `user_id`, `media_state`, `reward_token`, `likes_count`, `collection_count`, `provider_module`, `deleted_flag`, `created_time`, `updated_time`, `show_order`, `xgame_support`, `vr_mode`, `common`) VALUES ('1541', 'Melodies of the Soul: A Tale of Love and Inspiration', NULL, 'https://cdn.metaxsire.com/video/1MelodiesoftheSoulATaleofLoveandInspirationmp4.mp4_YYQDJW.mp4', NULL, 'https://cdn.metaxsire.com/media_resource/1_Melodies_of_the_Soul_A_Tale_of_Love_and_Inspiration_cover.png', 992, 512, 0, 0, 'audio', 'public', 'metaxsire', 2, 0, 0, 5122, 'recommend:novel', 1, '2025-05-20 18:42:35', '2025-05-20 18:42:37', 902, 0, 0, b'1');
INSERT INTO `toy`.`media_resource` (`id`, `media_name`, `introduce`, `media_url`, `author`, `media_cover_url`, `media_cover_height`, `media_cover_width`, `media_size`, `service_level_limits`, `media_category`, `visibility`, `user_id`, `media_state`, `reward_token`, `likes_count`, `collection_count`, `provider_module`, `deleted_flag`, `created_time`, `updated_time`, `show_order`, `xgame_support`, `vr_mode`, `common`) VALUES ('1539', 'The Soul\'s Connection', NULL, 'https://cdn.metaxsire.com/video/3TheSoulsConnectionmp4.mp4_W32ITF.mp4', NULL, 'https://cdn.metaxsire.com/media_resource/3_The_Soul\'s_Connection.png', 992, 512, 0, 0, 'audio', 'public', 'metaxsire', 2, 0, 0, 4652, 'recommend:novel', 1, '2025-05-20 18:42:35', '2025-05-20 18:42:37', 684, 0, 0, b'1');
INSERT INTO `toy`.`media_resource` (`id`, `media_name`, `introduce`, `media_url`, `author`, `media_cover_url`, `media_cover_height`, `media_cover_width`, `media_size`, `service_level_limits`, `media_category`, `visibility`, `user_id`, `media_state`, `reward_token`, `likes_count`, `collection_count`, `provider_module`, `deleted_flag`, `created_time`, `updated_time`, `show_order`, `xgame_support`, `vr_mode`, `common`) VALUES ('1538', 'The Eternal Canvas of Love', NULL, 'https://cdn.metaxsire.com/video/2TheEternalCanvasofLovemp4.mp4_JA0U7J.mp4', NULL, 'https://cdn.metaxsire.com/media_resource/2_The_Eternal_Canvas_of_Love.png', 992, 512, 0, 0, 'audio', 'public', 'metaxsire', 2, 0, 0, 3563, 'recommend:novel', 1, '2025-05-20 18:05:58', '2025-05-20 18:06:00', 568, 0, 0, b'1');
INSERT INTO `toy`.`media_resource` (`id`, `media_name`, `introduce`, `media_url`, `author`, `media_cover_url`, `media_cover_height`, `media_cover_width`, `media_size`, `service_level_limits`, `media_category`, `visibility`, `user_id`, `media_state`, `reward_token`, `likes_count`, `collection_count`, `provider_module`, `deleted_flag`, `created_time`, `updated_time`, `show_order`, `xgame_support`, `vr_mode`, `common`) VALUES ('1540', 'Whispers of the Heart', NULL, 'https://cdn.metaxsire.com/video/4WhispersoftheHeartmp4.mp4_CEX2UL.mp4', NULL, 'https://cdn.metaxsire.com/media_resource/4_Whispers_of_the_Heart3.png', 992, 512, 0, 0, 'audio', 'public', 'metaxsire', 2, 0, 0, 4222, 'recommend:novel', 1, '2025-05-20 18:42:35', '2025-05-20 18:42:37', 508, 0, 0, b'1');

INSERT INTO `toy`.`recommond_table` (`id`, `name`, `tag`, `introduce`, `poster`, `author`, `instruct_path`, `status`, `file_path`, `vr_video_url`, `type`, `duration`, `image_height`, `image_width`, `service_level_limits`, `deleted_flag`, `create_time`, `update_time`, `likes_count`, `collection_count`, `fake_collection_count`, `is_old_version`, `novel_text_url`, `show_order`, `first_frame_url`, `gender`, `selected_level`, `xgame_supported`, `vr_mode`) VALUES (1541, 'Melodies of the Soul: A Tale of Love and Inspiration', NULL, NULL, NULL, NULL, 'https://cdn.metaxsire.com/media_resource/1_Melodies_of_the_Soul_A_Tale_of_Love_and_Inspiration.json', 1, NULL, NULL, 'audio', 172000, 992, 512, 0, 1, '2025-05-20 18:45:41', '2025-05-20 18:45:44', 0, 0, 5122, NULL, 'https://cdn.metaxsire.com/media_resource/1_Melodies_of_the_Soul_A_Tale_of_Love_and_Inspiration.txt', 43, NULL, NULL, 0, b'0', 0);
INSERT INTO `toy`.`recommond_table` (`id`, `name`, `tag`, `introduce`, `poster`, `author`, `instruct_path`, `status`, `file_path`, `vr_video_url`, `type`, `duration`, `image_height`, `image_width`, `service_level_limits`, `deleted_flag`, `create_time`, `update_time`, `likes_count`, `collection_count`, `fake_collection_count`, `is_old_version`, `novel_text_url`, `show_order`, `first_frame_url`, `gender`, `selected_level`, `xgame_supported`, `vr_mode`) VALUES (1540, 'Whispers of the Heart', NULL, NULL, 'https://cdn.metaxsire.com/media_resource/4_Whispers_of_the_Heart3.png', NULL, 'https://cdn.metaxsire.com/media_resource/4_Whispers_of_the_Heart.json', 1, NULL, NULL, 'audio', 171000, 992, 512, 0, 1, '2025-05-20 18:45:41', '2025-05-20 18:45:44', 0, 0, 4222, NULL, 'https://cdn.metaxsire.com/media_resource/4_Whispers_of_the_Heart.txt', 694, NULL, NULL, 0, b'0', 0);
INSERT INTO `toy`.`recommond_table` (`id`, `name`, `tag`, `introduce`, `poster`, `author`, `instruct_path`, `status`, `file_path`, `vr_video_url`, `type`, `duration`, `image_height`, `image_width`, `service_level_limits`, `deleted_flag`, `create_time`, `update_time`, `likes_count`, `collection_count`, `fake_collection_count`, `is_old_version`, `novel_text_url`, `show_order`, `first_frame_url`, `gender`, `selected_level`, `xgame_supported`, `vr_mode`) VALUES (1539, 'The Soul\'s Connection', NULL, NULL, NULL, NULL, 'https://cdn.metaxsire.com/media_resource/3_The_Soul\'s_Connection.json', 1, NULL, NULL, 'audio', 245000, 992, 512, 0, 1, '2025-05-20 18:39:35', '2025-05-20 18:39:37', 0, 0, 4652, NULL, 'https://cdn.metaxsire.com/media_resource/3TheSoulsConnectionmp4.mp4_W32ITF.txt', 249, NULL, NULL, 0, b'0', 0);
INSERT INTO `toy`.`recommond_table` (`id`, `name`, `tag`, `introduce`, `poster`, `author`, `instruct_path`, `status`, `file_path`, `vr_video_url`, `type`, `duration`, `image_height`, `image_width`, `service_level_limits`, `deleted_flag`, `create_time`, `update_time`, `likes_count`, `collection_count`, `fake_collection_count`, `is_old_version`, `novel_text_url`, `show_order`, `first_frame_url`, `gender`, `selected_level`, `xgame_supported`, `vr_mode`) VALUES (1538, 'The Eternal Canvas of Love', NULL, NULL, NULL, NULL, 'https://cdn.metaxsire.com/media_resource/2_The_Eternal_Canvas_of_Love.json', 1, NULL, NULL, 'audio', 144000, 992, 512, 0, 1, '2025-05-20 18:13:02', '2025-05-20 18:13:05', 0, 0, 3563, NULL, 'https://cdn.metaxsire.com/media_resource/2_The_Eternal_Canvas_of_Love.txt', 308, NULL, NULL, 0, b'0', 0);
